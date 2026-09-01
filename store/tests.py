import json
from decimal import Decimal
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from attendance.models import COMMERCIAL_ADVISOR_POSITION, Employee
from catalog.models import Category, Product
from stock.models import StockBalance
from store.models import Role, Store, StoreMembership

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


def make_logo_upload(filename="store-logo.png"):
    buffer = BytesIO()
    Image.new("RGB", (24, 24), color="#1976d2").save(buffer, format="PNG")
    return SimpleUploadedFile(filename, buffer.getvalue(), content_type="image/png")


class TestStoreAPI:
    def test_pointage_only_user_sees_active_stores_without_memberships(self):
        user = User.objects.create_user(
            email="pointage-stores@example.com",
            password="securepass123",
            pointage_only=True,
        )
        Role.objects.get_or_create(
            code=Role.Codes.DIRECTION,
            defaults={"name": "Direction", "rank": 1},
        )
        active_store = Store.objects.create(
            name="POINTAGE ACTIVE",
            code="POINTAGE_ACTIVE",
            is_active=True,
        )
        Store.objects.create(
            name="POINTAGE INACTIVE",
            code="POINTAGE_INACTIVE",
            is_active=False,
        )
        client = authenticated_client(user)

        response = client.get(reverse("stores-mine"))

        assert response.status_code == status.HTTP_200_OK
        stores_by_id = {item["store"]["id"]: item for item in response.data}
        assert active_store.pk in stores_by_id
        assert stores_by_id[active_store.pk]["role"]["code"] == Role.Codes.DIRECTION
        assert not StoreMembership.objects.filter(user=user).exists()

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

    def test_staff_can_create_store_with_logo_and_absolute_api_representation(
        self, settings, tmp_path
    ):
        settings.MEDIA_ROOT = tmp_path
        user = make_user("store-logo-admin@example.com", is_staff=True)
        Role.objects.get_or_create(
            code=Role.Codes.DIRECTION,
            defaults={"name": "Direction", "rank": 1},
        )
        client = authenticated_client(user)

        response = client.post(
            reverse("stores-list"),
            {
                "name": "STORE LOGO",
                "code": "STORE_LOGO",
                "logo": make_logo_upload(),
                "is_active": "true",
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        store = Store.objects.get(code="STORE_LOGO")
        assert store.logo.name.startswith("store_logos/")
        assert store.logo.name.endswith(".png")
        assert response.data["logo"] == f"http://testserver{store.logo.url}"
        assert store.history.latest().logo == store.logo.name

        detail_response = client.get(reverse("stores-detail", args=[store.pk]))
        mine_response = client.get(reverse("stores-mine"))

        assert detail_response.status_code == status.HTTP_200_OK
        assert detail_response.data["logo"] == response.data["logo"]

        logo_response = client.get(reverse("stores-logo", args=[store.pk]))
        assert logo_response.status_code == status.HTTP_200_OK
        assert logo_response["Content-Type"] == "image/png"
        assert b"".join(logo_response.streaming_content).startswith(b"\x89PNG")

        nested_store = next(
            item["store"] for item in mine_response.data if item["store"]["id"] == store.pk
        )
        assert nested_store["logo"] == response.data["logo"]

    def test_staff_can_edit_logo_and_json_lists_through_multipart(
        self, settings, tmp_path
    ):
        settings.MEDIA_ROOT = tmp_path
        user = make_user("store-logo-edit-admin@example.com", is_staff=True)
        member = make_user("store-logo-member@example.com")
        role, _ = Role.objects.get_or_create(
            code=Role.Codes.RESPONSABLE,
            defaults={"name": "Responsable", "rank": 2},
        )
        store = Store.objects.create(name="STORE LOGO EDIT", code="STORE_LOGO_EDIT")
        client = authenticated_client(user)

        response = client.patch(
            reverse("stores-detail", args=[store.pk]),
            {
                "logo": make_logo_upload("edited-logo.png"),
                "managed_by": json.dumps([{"pk": member.pk, "role": role.code}]),
                "employees": json.dumps(
                    [{"first_name": "Sara", "last_name": "Amrani"}]
                ),
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        store.refresh_from_db()
        assert response.data["logo"] == f"http://testserver{store.logo.url}"
        assert StoreMembership.objects.filter(
            store=store, user=member, role=role, is_active=True
        ).exists()
        assert Employee.objects.filter(
            store=store,
            first_name="Sara",
            last_name="Amrani",
            is_active=True,
        ).exists()

        remove_response = client.patch(
            reverse("stores-detail", args=[store.pk]),
            {"remove_logo": "true"},
            format="multipart",
        )

        assert remove_response.status_code == status.HTTP_200_OK, remove_response.data
        store.refresh_from_db()
        assert not store.logo
        assert remove_response.data["logo"] is None
        assert store.history.latest().logo in {None, ""}

    def test_staff_can_create_store_with_assigned_users(self):
        user = make_user("store-owner@example.com", is_staff=True)
        member = make_user("store-member@example.com")
        role, _ = Role.objects.get_or_create(
            code=Role.Codes.RESPONSABLE,
            defaults={"name": "Responsable", "rank": 2},
        )
        client = authenticated_client(user)

        response = client.post(
            reverse("stores-list"),
            {
                "name": "MBR ASSIGNED",
                "code": "MBR_ASSIGNED",
                "managed_by": [{"pk": member.pk, "role": role.code}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        store = Store.objects.get(code="MBR_ASSIGNED")
        membership = StoreMembership.objects.get(user=member, store=store)
        assert membership.role == role
        assert response.data["managed_by"][0]["pk"] == member.pk

    def test_staff_can_create_store_employees_without_app_accounts(self):
        user = make_user("store-employee-admin@example.com", is_staff=True)
        client = authenticated_client(user)
        user_count = User.objects.count()

        response = client.post(
            reverse("stores-list"),
            {
                "name": "STORE EMPLOYEES",
                "code": "STORE_EMPLOYEES",
                "employees": [
                    {"first_name": "Sara", "last_name": "Amrani"},
                    {"first_name": "Youssef", "last_name": "Alaoui"},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        store = Store.objects.get(code="STORE_EMPLOYEES")
        employees = Employee.objects.filter(store=store).order_by("first_name")
        assert list(employees.values_list("first_name", "last_name")) == [
            ("Sara", "Amrani"),
            ("Youssef", "Alaoui"),
        ]
        assert all(employee.user_id is None for employee in employees)
        assert all(employee.position == COMMERCIAL_ADVISOR_POSITION for employee in employees)
        assert User.objects.count() == user_count
        assert [item["full_name"] for item in response.data["employees"]] == [
            "Sara Amrani",
            "Youssef Alaoui",
        ]

    def test_store_update_deactivates_removed_pointage_employee(self):
        user = make_user("store-employee-update@example.com", is_staff=True)
        store = Store.objects.create(name="STORE UPDATE", code="STORE_UPDATE")
        kept = Employee.objects.create(
            store=store,
            first_name="Sara",
            last_name="Amrani",
            full_name="Sara Amrani",
        )
        removed = Employee.objects.create(
            store=store,
            first_name="Youssef",
            last_name="Alaoui",
            full_name="Youssef Alaoui",
        )
        client = authenticated_client(user)

        response = client.patch(
            reverse("stores-detail", kwargs={"pk": store.pk}),
            {
                "employees": [
                    {
                        "id": kept.pk,
                        "first_name": "Sara",
                        "last_name": "Amrani",
                    }
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        kept.refresh_from_db()
        removed.refresh_from_db()
        assert kept.is_active is True
        assert removed.is_active is False

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

    def test_staff_cannot_delete_store_with_stock_data(self):
        user = make_user("store-delete-stock@example.com", is_staff=True)
        client = authenticated_client(user)
        store = Store.objects.create(name="Store With Stock", code="STORE_STOCK")
        category = Category.objects.create(code="STORE_STOCK_CAT", name="Store stock category")
        product = Product.objects.create(
            reference="STORE-STOCK-PRODUCT",
            barcode="STORE-STOCK-PRODUCT",
            name="Store stock product",
            category=category,
            purchase_price=Decimal("1.00"),
            counter_price=Decimal("2.00"),
        )
        StockBalance.objects.create(store=store, product=product, quantity=Decimal("1.000"))

        response = client.delete(reverse("stores-detail", args=[store.pk]), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Store.objects.filter(pk=store.pk).exists()

    def test_bulk_delete_blocks_store_with_business_data(self):
        user = make_user("store-bulk-stock@example.com", is_staff=True)
        client = authenticated_client(user)
        empty_store = Store.objects.create(name="Store Empty Bulk", code="STORE_EMPTY_BULK")
        blocked_store = Store.objects.create(name="Store Blocked Bulk", code="STORE_BLOCKED_BULK")
        category = Category.objects.create(code="STORE_BLOCK_CAT", name="Store blocked category")
        product = Product.objects.create(
            reference="STORE-BLOCK-PRODUCT",
            barcode="STORE-BLOCK-PRODUCT",
            name="Store blocked product",
            category=category,
            purchase_price=Decimal("1.00"),
            counter_price=Decimal("2.00"),
        )
        StockBalance.objects.create(store=blocked_store, product=product, quantity=Decimal("1.000"))

        response = client.delete(
            reverse("stores-bulk-delete"),
            {"ids": [empty_store.pk, blocked_store.pk]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Store.objects.filter(pk__in=[empty_store.pk, blocked_store.pk]).count() == 2

    def test_bulk_delete_requires_ids(self):
        user = make_user("store-empty-delete@example.com", is_staff=True)
        client = authenticated_client(user)

        response = client.delete(reverse("stores-bulk-delete"), {"ids": []}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
