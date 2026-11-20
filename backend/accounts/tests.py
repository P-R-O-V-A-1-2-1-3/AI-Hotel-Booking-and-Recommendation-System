from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class AuthTests(APITestCase):
    def test_register_returns_tokens_and_traveler_role(self):
        res = self.client.post('/api/auth/register/', {
            'email': 'New.User@Example.com', 'password': 'S3cure-pass-77', 'firstName': 'New',
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', res.data)
        self.assertEqual(res.data['user']['email'], 'new.user@example.com')
        self.assertEqual(res.data['user']['role'], 'traveler')

    def test_register_rejects_duplicate_email_and_weak_password(self):
        User.objects.create_user(email='taken@example.com', password='S3cure-pass-77')
        res = self.client.post('/api/auth/register/', {'email': 'TAKEN@example.com', 'password': 'S3cure-pass-77',
                                                        'firstName': 'X'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.client.post('/api/auth/register/', {'email': 'weak@example.com', 'password': '123',
                                                        'firstName': 'X'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('non_field_errors', res.data)

    def test_register_cannot_self_assign_admin_role(self):
        res = self.client.post('/api/auth/register/', {'email': 'sneaky@example.com', 'password': 'S3cure-pass-77',
                                                        'firstName': 'S', 'role': 'admin'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.get(email='sneaky@example.com').role, 'traveler')

    def test_login_with_email_and_me(self):
        User.objects.create_user(email='nadia@example.com', password='S3cure-pass-77', first_name='Nadia')
        res = self.client.post('/api/auth/login/', {'email': 'nadia@example.com', 'password': 'S3cure-pass-77'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['user']['firstName'], 'Nadia')

        self.assertEqual(self.client.get('/api/auth/me/').status_code, status.HTTP_401_UNAUTHORIZED)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {res.data["access"]}')
        me = self.client.get('/api/auth/me/')
        self.assertEqual(me.data['email'], 'nadia@example.com')

    def test_login_wrong_password(self):
        User.objects.create_user(email='nadia@example.com', password='S3cure-pass-77')
        res = self.client.post('/api/auth/login/', {'email': 'nadia@example.com', 'password': 'nope'})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
