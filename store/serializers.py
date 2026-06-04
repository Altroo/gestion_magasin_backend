from django.contrib.auth import get_user_model
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from store.models import Role, Store, StoreMembership

User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "name", "rank"]


class StoreSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "code",
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


class StoreDetailSerializer(StoreSerializer):
    managed_by = StoreManagedByItemSerializer(many=True, write_only=True, required=False)

    class Meta(StoreSerializer.Meta):
        fields = StoreSerializer.Meta.fields + ["managed_by"]

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

    def create(self, validated_data):
        managed_items = validated_data.pop("managed_by", None)
        store = super().create(validated_data)
        if managed_items is not None:
            self.update_memberships(store, managed_items)
        return store

    def update(self, instance, validated_data):
        managed_items = validated_data.pop("managed_by", None)
        instance = super().update(instance, validated_data)
        if managed_items is not None:
            self.update_memberships(instance, managed_items)
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
