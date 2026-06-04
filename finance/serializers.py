from rest_framework import serializers

from finance.models import Expense, ExpenseCategory


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "code", "name", "is_active", "date_created", "date_updated"]
        read_only_fields = ["date_created", "date_updated"]


class ExpenseSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id",
            "store",
            "store_name",
            "category",
            "category_name",
            "label",
            "amount",
            "payment_status",
            "payment_mode",
            "expense_date",
            "note",
            "created_by",
            "created_by_email",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["created_by", "date_created", "date_updated"]

