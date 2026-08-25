# Copyright 2022 by Open Kilt LLC. All rights reserved.
# This file is part of the OpenRepo Repository Management Software (OpenRepo)
# OpenRepo is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License
# version 3 as published by the Free Software Foundation
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import requests
from .errors import ORNon200ResponseException, ORConnectionException, ORUnauthorizedException, ORInvalidRequestException
import json
import logging
import time

logger = logging.getLogger('openrepo_cli')

# methods are GET, OPTIONS, HEAD, POST, PUT, PATCH, or DELETE.
REQUEST_ENDPOINTS = {
    'list_repos': ('GET', '/api/repos/'),
    'list_packages': ('GET', '/api/<repo>/packages/'),
    'list_signingkeys': ('GET', '/api/signingkeys/'),
    'repo_details': ('GET', '/api/<repo>/'),
    'repo_create': ('POST', '/api/repos/'),
    'repo_update': ('PATCH', '/api/<repo>/'),
    'repo_delete': ('DELETE', '/api/<repo>/'),
    'upload': ('POST', '/api/<repo>/upload/'),
    'upload_status': ('GET', '/api/upload-status/<task_id>/'),
    'package_delete': ('DELETE', '/api/<repo>/pkg/<package>/'),
    'package_detail': ('GET', '/api/<repo>/pkg/<package>/'),
    'package_copy': ('POST', '/api/<repo>/pkg/<package>/copy/'),
    'create_signingkey': ('POST', '/api/signingkeys/'),
    'delete_signingkey': ('DELETE', '/api/signingkeys/<fingerprint>/'),
    'download_signingkey': ('GET', '/api/signingkeys/<fingerprint>/download/'),
    'whoami': ('GET', '/api/whoami'),
}


def cli_method(func):
    '''Decorator for API functions so that we can autodetect the function and map the args to CLI commands'''
    func.cli_method = True
    return func


class RestInterface:

    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        if self.base_url.endswith('/'):
            self.base_url = self.base_url[:-1]

    @cli_method
    def package_copy(self, src_repo_uid, src_package_uid, dst_repo_uid):
        '''
        Copy a package from one repository to another
        '''
        return self._request('package_copy',
                             repo=src_repo_uid, package=src_package_uid,
                             postdata={
                                 'dest_repo_uid': dst_repo_uid
                             })

    @cli_method
    def package_promote(self, src_repo_uid, src_package_uid):
        '''
        Promote a package to the repo configured as "promote_to"
        '''
        # Promotion is just a copy to the configured "promote_to" repo
        repo_info = self.repo_details(src_repo_uid)
        if repo_info['promote_to'] is None:
            raise ORInvalidRequestException(
                f"The target repo {src_repo_uid} does not have a configured promotion target"
            )

        return self.package_copy(src_repo_uid, src_package_uid, repo_info['promote_to'])

    @cli_method
    def package_detail(self, repo_uid, package_uid):
        '''
        Show detailed information about a package
        '''

        return self._request('package_detail', repo=repo_uid, package=package_uid)

    @cli_method
    def list_repos(self):
        '''
        List all repositories
        '''
        return self._request('list_repos')

    @cli_method
    def list_packages(self, repo_uid):
        '''
        List packages in a repository
        '''
        return self._request('list_packages', repo=repo_uid)

    @cli_method
    def list_signingkeys(self):
        '''
        List all signing keys
        '''
        return self._request('list_signingkeys')

    @cli_method
    def repo_create(self, repo_uid, repo_type, signing_key):
        '''
        Create a new repository
        '''
        return self._request('repo_create', postdata={
            'repo_uid': repo_uid,
            'repo_type': repo_type,
            'signing_key': signing_key
        })

    @cli_method
    def repo_update(self, repo_uid, signing_key="", retention_policy="", multi_arch="", promote_to=""):
        '''
        Update repository settings (partial update)
        '''
        postdata = {}
        if signing_key:
            postdata['signing_key'] = signing_key
        if retention_policy:
            postdata['retention_policy'] = retention_policy
        if multi_arch:
            postdata['multi_arch'] = multi_arch.lower() in ('true', '1', 'yes')
        if promote_to:
            postdata['promote_to'] = promote_to
        return self._request('repo_update', repo=repo_uid, postdata=postdata)

    @cli_method
    def repo_delete(self, repo_uid):
        '''
        Delete a repository
        '''
        return self._request('repo_delete', repo=repo_uid)

    @cli_method
    def repo_details(self, repo_uid):
        '''
        Show detailed information about a particular repo
        '''
        return self._request('repo_details', repo=repo_uid)

    @cli_method
    def package_delete(self, repo_uid, package_uid):
        '''
        Delete a package from a repository
        '''
        return self._request('package_delete', repo=repo_uid, package=package_uid)

    @cli_method
    def create_signingkey(self, name, email):
        '''
        Generate a new PGP signing key
        '''
        return self._request('create_signingkey', postdata={
            'name': name,
            'email': email
        })

    @cli_method
    def delete_signingkey(self, fingerprint):
        '''
        Delete a PGP signing key
        '''
        return self._request('delete_signingkey', fingerprint=fingerprint)

    @cli_method
    def download_signingkey(self, fingerprint):
        '''
        Download the public key (.asc) for a signing key
        '''
        return self._request('download_signingkey', fingerprint=fingerprint)

    @cli_method
    def whoami(self):
        '''
        Show current user info and API token
        '''
        return self._request('whoami')

    def upload(self, filepath, repo_uid, overwrite, wait=True, poll_interval=2, timeout=300):
        '''
        Upload package files to a repo
        '''
        postdata = None
        if overwrite:
            postdata = {'overwrite': '1'}

        with open(filepath, 'rb') as package_file:
            files = {'package_file': package_file}
            response = self._request('upload', repo=repo_uid, files=files, postdata=postdata)

        if not wait:
            return response

        # Poll upload status until completion or timeout
        task_id = response.get('task_id')
        if not task_id:
            return response

        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(poll_interval)
            try:
                status_resp = self._request('upload_status', task_id=task_id)
                status = status_resp.get('status', '')
                if status in ('completed', 'failed'):
                    if status == 'failed':
                        error_msg = status_resp.get('error_message', 'Unknown error')
                        logger.error(f"Upload processing failed: {error_msg}")
                    return status_resp
            except Exception as e:
                logger.warning(f"Error polling upload status: {e}")

        logger.warning(f"Upload status poll timed out after {timeout}s for task {task_id}")
        return response

    def _request(self, endpoint_name, repo=None, package=None, task_id=None,
                 fingerprint=None, query_args=None, postdata=None, files=None):
        endpoint = REQUEST_ENDPOINTS[endpoint_name]
        method = endpoint[0]
        url = self.base_url + endpoint[1]

        if repo is not None:
            url = url.replace('<repo>', repo)
        if package is not None:
            url = url.replace('<package>', package)
        if task_id is not None:
            url = url.replace('<task_id>', task_id)
        if fingerprint is not None:
            url = url.replace('<fingerprint>', fingerprint)

        if query_args is not None:
            url += '?'
            for k, v in query_args.items():
                url += f'{k}={v}&'
            url = url[:-1]

        auth_header = {'Authorization': f'Token {self.api_key}'}
        try:
            logger.debug(f"Making {method} request to {url}")
            resp = requests.request(method, url, files=files, data=postdata, headers=auth_header, timeout=60)
            logger.debug(f"Received {resp.status_code} response")
            logger.debug(f"Content: {resp.content}")
            if resp.status_code == 401:
                raise ORUnauthorizedException("Unauthorized")
            elif resp.status_code < 200 or resp.status_code > 299:
                raise ORNon200ResponseException(f"HTTP Response code {resp.status_code}",
                                                resp.status_code, error_content=resp.content.decode('utf-8'))

            if len(resp.content) == 0:
                return {}
            return json.loads(resp.content)
        except requests.exceptions.ConnectionError:
            raise ORConnectionException("Unable to connect to server")

    def get_cli_functions(self):
        # Make the CLI app a little easier by returning a nicely formatted
        # list of all function names and arguments.  Only includes those that have been
        # flagged with the decorator "cli_method"
        # From this we can programmatically build the CLI args

        import inspect

        response = []

        methodList = []
        for method_name in dir(self):
            try:
                if callable(getattr(self, method_name)):
                    methodList.append(str(method_name))
            except Exception:
                methodList.append(str(method_name))
        # processFunc = (lambda s: ' '.join(s.split())) or (lambda s: s)
        for method in methodList:
            try:
                method_obj = getattr(self, method)
                is_cli = hasattr(method_obj, 'cli_method')
                if not is_cli:
                    continue
                response.append({'function_name': method,
                                 'args': inspect.signature(method_obj),
                                 'doc': method_obj.__doc__
                                 })

            except BaseException:
                logger.exception(f"Failed to infer args for CLI command {method}")

        return response
