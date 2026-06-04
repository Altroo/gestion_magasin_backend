from django.contrib.auth import get_user_model
from rest_framework import serializers

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
            "members_count",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["date_created", "date_updated"]


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

