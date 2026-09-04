from django.contrib.auth import get_user_model
from repo.models import PGPSigningKey, Repository
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase


def _make_admin(username: str):
    User = get_user_model()
    User.objects.filter(username=username).delete()
    return User.objects.create_superuser(username=username, password='password123')


def _make_user(username: str):
    User = get_user_model()
    User.objects.filter(username=username).delete()
    return User.objects.create_user(username=username, password='password123')


def _make_key():
    return PGPSigningKey.objects.create(
        name="Test Key", email="test@example.com",
        fingerprint="ABCDEF1234567890",
        public_key_pem="dummy public", private_key_pem="dummy private",
    )


class CircularPromoteDetectionTest(APITestCase):
    """Tests for circular promote_to detection in RepoDetailSerializer"""

    def setUp(self):
        self.admin = _make_admin('circ-admin')
        self.token = Token.objects.get(user=self.admin).key
        self.auth = f'Token {self.token}'
        self.signing_key = _make_key()
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
