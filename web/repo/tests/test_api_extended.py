from repo.models import Repository
from rest_framework import status
from rest_framework.test import APITestCase

from repo.tests.fixtures import make_admin, make_signing_key


class CircularPromoteDetectionTest(APITestCase):
    """Tests for circular promote_to detection in RepoDetailSerializer"""

    def setUp(self):
        self.admin, self.token, self.auth = make_admin('circ-admin')
        self.signing_key = make_signing_key(fingerprint="ABCDEF1234567890")
        self.repo_a = Repository.objects.create(repo_uid='repo-a', repo_type='deb')
        self.repo_b = Repository.objects.create(repo_uid='repo-b', repo_type='deb')

    def test_linear_promote_chain_succeeds(self):
        response = self.client.put(
            '/api/repo-a/',
            {'repo_uid': 'repo-a', 'repo_type': 'deb',
             'promote_to': 'repo-b', 'signing_key': self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=self.auth, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_circular_promote_direct(self):
        self.client.put(
            '/api/repo-a/',
            {'repo_uid': 'repo-a', 'repo_type': 'deb',
             'promote_to': 'repo-b', 'signing_key': self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=self.auth, format='json',
        )
        response = self.client.put(
            '/api/repo-b/',
            {'repo_uid': 'repo-b', 'repo_type': 'deb',
             'promote_to': 'repo-a', 'signing_key': self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=self.auth, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('promote_to', response.data.get('detail', ''))

    def test_multiple_repos_pointing_to_same_target(self):
        self.client.put(
            '/api/repo-a/',
            {'repo_uid': 'repo-a', 'repo_type': 'deb',
             'promote_to': 'repo-b', 'signing_key': self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=self.auth, format='json',
        )
        Repository.objects.create(repo_uid='repo-c', repo_type='deb')
        response = self.client.put(
            '/api/repo-c/',
            {'repo_uid': 'repo-c', 'repo_type': 'deb',
             'promote_to': 'repo-b', 'signing_key': self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=self.auth, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
