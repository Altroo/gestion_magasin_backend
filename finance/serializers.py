from rest_framework import serializers

from finance.models import Expense, ExpenseCategory
from sales.models import PaymentMode


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "code", "name", "is_active", "date_created", "date_updated"]
        read_only_fields = ["date_created", "date_updated"]


class ExpenseSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    payment_mode_name = serializers.SerializerMethodField()
    invoice_file_url = serializers.SerializerMethodField()

    def get_payment_mode_name(self, obj):
        if not hasattr(self, "_payment_mode_names"):
            self._payment_mode_names = dict(
                PaymentMode.objects.filter(is_active=True).values_list("code", "name")
            )
        return self._payment_mode_names.get(obj.payment_mode) or obj.get_payment_mode_display()

    def get_invoice_file_url(self, obj):
        if not obj.invoice_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.invoice_file.url)
        return obj.invoice_file.url

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
            "payment_mode_name",
            "expense_date",
            "invoice_file",
            "invoice_file_url",
            "note",
            "created_by",
            "created_by_email",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["created_by", "date_created", "date_updated", "invoice_file_url"]
