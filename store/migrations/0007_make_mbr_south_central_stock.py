from django.db import migrations


def move_central_stock(apps, schema_editor):
    db = schema_editor.connection.alias
    Store = apps.get_model("store", "Store")
    Membership = apps.get_model("store", "StoreMembership")
    Balance = apps.get_model("stock", "StockBalance")
    south, _ = Store.objects.using(db).get_or_create(
        code="mbr-south", defaults={"name": "MBR SOUTH", "is_active": True}
    )
    legacy = Store.objects.using(db).filter(code="mbr-stock").first()
    if legacy and legacy.pk != south.pk:
        for balance in Balance.objects.using(db).filter(store_id=legacy.pk):
            destination = Balance.objects.using(db).filter(
                store_id=south.pk, product_id=balance.product_id
            ).first()
            if destination:
                destination.quantity += balance.quantity
                destination.save(using=db, update_fields=["quantity", "date_updated"])
                balance.delete(using=db)
            else:
                balance.store_id = south.pk
                balance.save(using=db, update_fields=["store", "date_updated"])
        for membership in Membership.objects.using(db).filter(store_id=legacy.pk):
            if Membership.objects.using(db).filter(store_id=south.pk, user_id=membership.user_id).exists():
                membership.is_active = False
                membership.save(using=db, update_fields=["is_active", "date_updated"])
            else:
                membership.store_id = south.pk
                membership.save(using=db, update_fields=["store", "date_updated"])
        for app_label, model_name, field in (
            ("stock", "StockMovement", "store_id"),
            ("stock", "StockAddRequest", "store_id"),
            ("stock", "Purchase", "store_id"),
            ("stock", "InventorySession", "store_id"),
            ("catalog", "ProductImportBatch", "store_id"),
            ("sales", "Sale", "store_id"),
            ("notification", "Notification", "store_id"),
        ):
            model = apps.get_model(app_label, model_name)
            model.objects.using(db).filter(**{field: legacy.pk}).update(**{field: south.pk})
        legacy.is_global_stock = False
        legacy.is_active = False
        legacy.save(using=db, update_fields=["is_global_stock", "is_active", "date_updated"])
    south.is_global_stock = True
    south.is_active = True
    south.save(using=db, update_fields=["is_global_stock", "is_active", "date_updated"])


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0006_historicalstore_logo_store_logo"),
        ("stock", "0006_alter_historicalinventoryline_note_and_more"),
        ("catalog", "0006_historicalproductstocktrackingitem_and_more"),
        ("sales", "0008_historicalsale_sale_type_sale_sale_type"),
        ("notification", "0003_historicalnotificationpreference_notify_stock_add_requests_and_more"),
    ]
    operations = [migrations.RunPython(move_central_stock, migrations.RunPython.noop)]
