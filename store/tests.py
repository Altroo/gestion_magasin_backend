import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from store.models import Store

pytestmark = pytest.mark.django_db

User = get_user_model()


def authenticated_client(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


def make_user(email, is_staff=False):
    return User.objects.create_user(
        email=email,
        password="securepass123",
        is_staff=is_staff,
    )


class TestStoreAPI:
    def test_staff_can_create_store(self):
        user = make_user("store-admin@example.com", is_staff=True)
        client = authenticated_client(user)

        response = client.post(
            reverse("stores-list"),
            {
                "name": "MBR TEST",
                "code": "MBR_TEST",
                "address": "Casablanca",
                "phone": "212600000000",
                "is_active": True,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Store.objects.filter(code="MBR_TEST").exists()

    def test_regular_user_cannot_create_store(self):
        user = make_user("store-user@example.com")
        client = authenticated_client(user)

        response = client.post(
            reverse("stores-list"),
            {"name": "Forbidden", "code": "FORBIDDEN"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_staff_can_search_and_filter_stores(self):
        user = make_user("store-search@example.com", is_staff=True)
        client = authenticated_client(user)
        Store.objects.create(name="MBR SOUTH TEST", code="MBR_SOUTH_TEST", is_active=True)
        Store.objects.create(name="Inactive store", code="INACTIVE", is_active=False)

        response = client.get(
            reverse("stores-list"), {"search": "south test", "is_active": "true"}
        )

        assert response.status_code == status.HTTP_200_OK
        names = [store["name"] for store in response.data["results"]]
        assert names == ["MBR SOUTH TEST"]

    def test_staff_can_filter_stores_with_comma_separated_boolean_values(self):
        user = make_user("store-csv-filter@example.com", is_staff=True)
        client = authenticated_client(user)
        active = Store.objects.create(name="CSV Active", code="CSV_ACTIVE", is_active=True)
        inactive = Store.objects.create(name="CSV Inactive", code="CSV_INACTIVE", is_active=False)

        response = client.get(reverse("stores-list"), {"is_active": "true,false"})

        assert response.status_code == status.HTTP_200_OK
        ids = {store["id"] for store in response.data["results"]}
        assert {active.id, inactive.id}.issubset(ids)

    def test_staff_can_bulk_delete_stores(self):
        user = make_user("store-delete@example.com", is_staff=True)
        client = authenticated_client(user)
        first = Store.objects.create(name="Store A", code="STORE_A")
        second = Store.objects.create(name="Store B", code="STORE_B")

        response = client.delete(
            reverse("stores-bulk-delete"),
            {"ids": [first.id, second.id]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["deleted"] >= 2
        assert not Store.objects.filter(id__in=[first.id, second.id]).exists()

    def test_bulk_delete_requires_ids(self):
        user = make_user("store-empty-delete@example.com", is_staff=True)
        client = authenticated_client(user)

        response = client.delete(reverse("stores-bulk-delete"), {"ids": []}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
