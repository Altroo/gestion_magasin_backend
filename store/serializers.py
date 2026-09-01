import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from attendance.models import COMMERCIAL_ADVISOR_POSITION, Employee
from store.models import Role, Store, StoreMembership

User = get_user_model()


class MultipartJsonListField(serializers.ListField):
    """Accept a normal JSON list or one JSON-encoded multipart form value."""

    default_error_messages = {
        "invalid_json": _("Cette valeur doit être une liste JSON valide."),
    }

    def get_value(self, dictionary):
        value = super().get_value(dictionary)
        if (
            isinstance(value, list)
            and len(value) == 1
            and isinstance(value[0], str)
            and value[0].lstrip().startswith("[")
        ):
            return value[0]
        return value

    def to_internal_value(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (TypeError, ValueError):
                self.fail("invalid_json")
        return super().to_internal_value(data)


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "name", "rank"]


class StoreSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(read_only=True)
    logo = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "code",
            "logo",
            "address",
            "phone",
            "is_active",
            "is_global_stock",
            "members_count",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["date_created", "date_updated"]


class StoreManagedByItemSerializer(serializers.Serializer):
    pk = serializers.IntegerField()
    role = serializers.CharField()


class StoreEmployeeItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    first_name = serializers.CharField(max_length=80)
    last_name = serializers.CharField(max_length=80)


class StoreDetailSerializer(StoreSerializer):
    managed_by = MultipartJsonListField(
        child=StoreManagedByItemSerializer(),
        write_only=True,
        required=False,
    )
    employees = MultipartJsonListField(
        child=StoreEmployeeItemSerializer(),
        write_only=True,
        required=False,
    )
    remove_logo = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta(StoreSerializer.Meta):
        fields = StoreSerializer.Meta.fields + ["managed_by", "employees", "remove_logo"]

    def validate(self, attrs):
        if attrs.get("remove_logo") and attrs.get("logo"):
            raise serializers.ValidationError(
                {
                    "logo": _(
                        "Un nouveau logo ne peut pas être envoyé en même temps que sa suppression."
                    )
                }
            )
        return attrs

    @staticmethod
    def _resolve_role(value):
        try:
            return Role.objects.get(code=value)
        except Role.DoesNotExist:
            try:
                return Role.objects.get(name=value)
            except Role.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"managed_by": _("Rôle magasin invalide.")}
                ) from exc

    @classmethod
    def update_memberships(cls, store, items):
        submitted_user_ids = []
        for item in items:
            user_id = item["pk"]
            if user_id in submitted_user_ids:
                raise serializers.ValidationError(
                    {"managed_by": _("Un utilisateur ne peut être affecté qu'une seule fois.")}
                )
            if not User.objects.filter(pk=user_id, is_active=True).exists():
                raise serializers.ValidationError(
                    {"managed_by": _("Utilisateur invalide pour ce magasin.")}
                )
            role = cls._resolve_role(item["role"])
            StoreMembership.objects.update_or_create(
                user_id=user_id,
                store=store,
                defaults={"role": role, "is_active": True},
            )
            submitted_user_ids.append(user_id)

        StoreMembership.objects.filter(store=store).exclude(
            user_id__in=submitted_user_ids
        ).delete()

    @staticmethod
    def update_employees(store, items):
        submitted_employee_ids = []
        submitted_names = set()
        for item in items:
            first_name = " ".join(item["first_name"].split())
            last_name = " ".join(item["last_name"].split())
            full_name = f"{first_name} {last_name}".strip()
            normalized_name = full_name.casefold()
            if normalized_name in submitted_names:
                raise serializers.ValidationError(
                    {"employees": _("Un employé ne peut être ajouté qu'une seule fois.")}
                )
            submitted_names.add(normalized_name)

            employee_id = item.get("id")
            if employee_id:
                try:
                    employee = Employee.objects.get(
                        pk=employee_id,
                        store=store,
                        user__isnull=True,
                    )
                except Employee.DoesNotExist as exc:
                    raise serializers.ValidationError(
                        {"employees": _("Employé invalide pour ce magasin.")}
                    ) from exc
            else:
                employee = Employee.objects.filter(
                    store=store,
                    full_name__iexact=full_name,
                    user__isnull=True,
                ).first()
                if employee is None:
                    if Employee.objects.filter(
                        store=store,
                        full_name__iexact=full_name,
                    ).exists():
                        raise serializers.ValidationError(
                            {"employees": _("Ce nom est déjà lié à un compte utilisateur.")}
                        )
                    employee = Employee(store=store, full_name=full_name)

            duplicate = Employee.objects.filter(
                store=store,
                full_name__iexact=full_name,
            ).exclude(pk=employee.pk)
            if duplicate.exists():
                raise serializers.ValidationError(
                    {"employees": _("Un employé avec ce nom existe déjà dans ce magasin.")}
                )

            employee.first_name = first_name
            employee.last_name = last_name
            employee.position = COMMERCIAL_ADVISOR_POSITION
            employee.is_active = True
            employee.save()
            submitted_employee_ids.append(employee.pk)

        Employee.objects.filter(store=store, user__isnull=True).exclude(
            pk__in=submitted_employee_ids
        ).update(is_active=False)

    @transaction.atomic
    def create(self, validated_data):
        managed_items = validated_data.pop("managed_by", None)
        employee_items = validated_data.pop("employees", None)
        validated_data.pop("remove_logo", False)
        store = super().create(validated_data)
        if managed_items is not None:
            self.update_memberships(store, managed_items)
        if employee_items is not None:
            self.update_employees(store, employee_items)
        return store

    @transaction.atomic
    def update(self, instance, validated_data):
        managed_items = validated_data.pop("managed_by", None)
        employee_items = validated_data.pop("employees", None)
        remove_logo = validated_data.pop("remove_logo", False)
        logo_changed = remove_logo or "logo" in validated_data
        previous_logo_name = instance.logo.name if instance.logo else None
        previous_logo_storage = instance.logo.storage if instance.logo else None
        if remove_logo:
            validated_data["logo"] = None
        instance = super().update(instance, validated_data)
        if managed_items is not None:
            self.update_memberships(instance, managed_items)
        if employee_items is not None:
            self.update_employees(instance, employee_items)
        if (
            logo_changed
            and previous_logo_name
            and previous_logo_storage
            and previous_logo_name != (instance.logo.name if instance.logo else None)
        ):
            transaction.on_commit(lambda: previous_logo_storage.delete(previous_logo_name))
        return instance

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["managed_by"] = [
            {
                "pk": membership.user_id,
                "role": membership.role.code,
                "role_name": membership.role.name,
                "membership_id": membership.pk,
            }
            for membership in instance.memberships.select_related("role", "user")
        ]
        representation["employees"] = [
            {
                "id": employee.pk,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "full_name": employee.full_name,
            }
            for employee in instance.employees.filter(
                user__isnull=True,
                is_active=True,
            ).order_by("first_name", "last_name")
        ]
        return representation


class StoreMembershipSerializer(serializers.ModelSerializer):
    role_code = serializers.CharField(source="role.code", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = StoreMembership
        fields = [
            "id",
            "user",
            "user_email",
            "user_name",
            "store",
            "store_name",
            "role",
            "role_code",
            "role_name",
            "is_active",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["date_created", "date_updated"]

    @staticmethod
    def get_user_name(instance):
        full_name = f"{instance.user.first_name} {instance.user.last_name}".strip()
        return full_name or instance.user.email


class UserStoreSerializer(serializers.ModelSerializer):
    role = RoleSerializer()
    store = StoreSerializer()

    class Meta:
        model = StoreMembership
        fields = ["id", "store", "role", "is_active"]
