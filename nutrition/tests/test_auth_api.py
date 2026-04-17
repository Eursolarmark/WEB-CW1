from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class AuthAPITests(APITestCase):
    def test_register_success(self):
        payload = {
            "username": "alice",
            "email": "alice@example.com",
            "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
        }

        response = self.client.post(reverse("auth-register"), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", response.data)
        self.assertEqual(response.data["username"], "alice")
        self.assertNotIn("password", response.data)
        self.assertTrue(User.objects.filter(username="alice").exists())

    def test_register_password_mismatch(self):
        payload = {
            "username": "alice",
            "email": "alice@example.com",
            "password": "StrongPass123!",
            "password_confirm": "StrongPass999!",
        }

        response = self.client.post(reverse("auth-register"), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("password_confirm", response.data["details"])

    def test_obtain_and_refresh_token(self):
        User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="StrongPass123!",
        )

        token_response = self.client.post(
            reverse("auth-token-obtain-pair"),
            {"username": "alice", "password": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(token_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", token_response.data)
        self.assertIn("refresh", token_response.data)

        refresh_response = self.client.post(
            reverse("auth-token-refresh"),
            {"refresh": token_response.data["refresh"]},
            format="json",
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_response.data)

    def test_obtain_token_with_email_identifier(self):
        User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="StrongPass123!",
        )

        response = self.client.post(
            reverse("auth-token-obtain-pair"),
            {"username": "alice@example.com", "password": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_auth_me_requires_authentication(self):
        response = self.client.get(reverse("auth-me"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_auth_me_returns_current_user(self):
        user = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="StrongPass123!",
        )
        self.client.force_authenticate(user=user)

        response = self.client.get(reverse("auth-me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], user.id)
        self.assertEqual(response.data["username"], "alice")
        self.assertEqual(response.data["email"], "alice@example.com")

    def test_logout_blacklists_refresh_token(self):
        User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="StrongPass123!",
        )
        token_response = self.client.post(
            reverse("auth-token-obtain-pair"),
            {"username": "alice", "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(token_response.status_code, status.HTTP_200_OK)

        access = token_response.data["access"]
        refresh = token_response.data["refresh"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        logout_response = self.client.post(
            reverse("auth-logout"),
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(logout_response.status_code, status.HTTP_205_RESET_CONTENT)

        refresh_response = self.client.post(
            reverse("auth-token-refresh"),
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_requires_authentication(self):
        response = self.client.post(
            reverse("auth-logout"),
            {"refresh": "dummy-token"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
