from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from attendance.models import AttendanceRecord, Employee
from catalog.models import Category, Product
from finance.models import Expense, ExpenseCategory
from sales.models import PaymentMode, Promotion, PromotionLine
from sales.services import create_sale
from stock.models import StockBalance, StockTransfer, StockTransferLine
from stock.services import validate_stock_transfer
from store.models import Role, Store, StoreMembership


class Command(BaseCommand):
    help = "Seed Gestion Magasin with demo stores, stock, promotions, sales, and attendance."

    def handle(self, *args, **options):
        with transaction.atomic():
            roles = self._roles()
            stores = self._stores()
            users = self._users(roles, stores)
            products = self._products()
            self._mbr_stock(stores["mbr_stock"], products)
            self._payment_modes()
            self._transfers(stores, products, users["admin"])
            self._promotions(stores["mbr_south"], products, users["seller"])
            self._sales(stores["mbr_south"], products, users["seller"])
            self._attendance(stores["mbr_south"])
            self._expenses(stores["mbr_south"])
        self.stdout.write(self.style.SUCCESS("Gestion Magasin demo data is ready."))

    def _roles(self):
        roles = {}
        for code, name, rank in [
            (Role.Codes.DIRECTION, "Direction", 1),
            (Role.Codes.RESPONSABLE, "Responsable", 2),
            (Role.Codes.VENDEUR, "Vendeur", 3),
            (Role.Codes.LECTURE, "Lecture", 4),
        ]:
            roles[code], _ = Role.objects.update_or_create(
                code=code,
                defaults={"name": name, "rank": rank},
            )
        return roles

    def _stores(self):
        mbr_stock, _ = Store.objects.update_or_create(
            code="mbr-stock",
            defaults={
                "name": "MBR Stock",
                "address": "Depot central",
                "phone": "",
                "is_active": True,
                "is_global_stock": True,
            },
        )
        mbr_south, _ = Store.objects.update_or_create(
            code="mbr-south",
            defaults={
                "name": "MBR SOUTH",
                "address": "Casablanca",
                "phone": "0522000000",
                "is_active": True,
                "is_global_stock": False,
            },
        )
        mbr_demo, _ = Store.objects.update_or_create(
            code="mbr-demo",
            defaults={
                "name": "MBR Demo",
                "address": "Rabat",
                "phone": "0537000000",
                "is_active": True,
                "is_global_stock": False,
            },
        )
        return {"mbr_stock": mbr_stock, "mbr_south": mbr_south, "mbr_demo": mbr_demo}

    def _users(self, roles, stores):
        User = get_user_model()
        admin, _ = User.objects.update_or_create(
            email="service-it@casadilusso.ma",
            defaults={
                "first_name": "Service",
                "last_name": "IT",
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
                "can_view": True,
                "can_print": True,
                "can_create": True,
                "can_edit": True,
                "can_delete": True,
                "can_create_promotion": True,
            },
        )
        admin.set_password("Altroo002")
        admin.save()
        seller, _ = User.objects.update_or_create(
            email="vendeur.demo@gestion-magasin.local",
            defaults={
                "first_name": "Vendeur",
                "last_name": "Demo",
                "is_active": True,
                "can_view": True,
                "can_print": True,
                "can_create": True,
                "can_edit": True,
                "can_delete": False,
                "can_create_promotion": True,
            },
        )
        seller.set_password("Altroo002")
        seller.save()
        for store in stores.values():
            StoreMembership.objects.update_or_create(
                user=admin,
                store=store,
                defaults={"role": roles[Role.Codes.DIRECTION], "is_active": True},
            )
        StoreMembership.objects.update_or_create(
            user=seller,
            store=stores["mbr_south"],
            defaults={"role": roles[Role.Codes.RESPONSABLE], "is_active": True},
        )
        return {"admin": admin, "seller": seller}

    def _products(self):
        family, _ = Category.objects.update_or_create(
            code="demo-boisson",
            defaults={"name": "Boissons", "is_active": True},
        )
        product_specs = [
            ("DEMO-EAU-50", "6111000000011", "Eau minerale 50cl", "3.50", "6.00", "25.000"),
            ("DEMO-JUS-OR", "6111000000028", "Jus orange 1L", "9.00", "16.00", "12.000"),
            ("DEMO-SODA", "6111000000035", "Soda canette", "5.00", "10.00", "18.000"),
        ]
        products = {}
        for reference, barcode, name, purchase_price, counter_price, alert in product_specs:
            product, _ = Product.objects.update_or_create(
                reference=reference,
                defaults={
                    "barcode": barcode,
                    "name": name,
                    "category": family,
                    "unit": "unite",
                    "purchase_price": Decimal(purchase_price),
                    "wholesale_price": Decimal(counter_price) - Decimal("2.00"),
                    "detail_price": Decimal(counter_price) - Decimal("1.00"),
                    "counter_price": Decimal(counter_price),
                    "default_stock_alert": Decimal(alert),
                    "is_active": True,
                },
            )
            products[reference] = product
        return products

    def _mbr_stock(self, store, products):
        opening = {
            "DEMO-EAU-50": ("240.000", "40.000"),
            "DEMO-JUS-OR": ("120.000", "20.000"),
            "DEMO-SODA": ("180.000", "30.000"),
        }
        for reference, (quantity, min_stock) in opening.items():
            product = products[reference]
            StockBalance.objects.update_or_create(
                store=store,
                product=product,
                defaults={
                    "quantity": Decimal(quantity),
                    "min_stock": Decimal(min_stock),
                    "average_cost": product.purchase_price,
                },
            )

    def _payment_modes(self):
        PaymentMode.objects.update_or_create(
            code="cash",
            defaults={"name": "Especes", "is_credit": False, "is_active": True},
        )
        PaymentMode.objects.update_or_create(
            code="credit",
            defaults={"name": "Credit client", "is_credit": True, "is_active": True},
        )

    def _transfers(self, stores, products, user):
        if StockTransfer.objects.filter(reference="DEMO-TR-001").exists():
            return
        transfer = StockTransfer.objects.create(
            source_store=stores["mbr_stock"],
            target_store=stores["mbr_south"],
            reference="DEMO-TR-001",
            transfer_date=timezone.localdate(),
            status=StockTransfer.Statuses.DRAFT,
            created_by=user,
            note="Dotation initiale demo",
        )
        for reference, quantity in {
            "DEMO-EAU-50": "60.000",
            "DEMO-JUS-OR": "35.000",
            "DEMO-SODA": "45.000",
        }.items():
            StockTransferLine.objects.create(
                transfer=transfer,
                product=products[reference],
                quantity=Decimal(quantity),
            )
        validate_stock_transfer(transfer=transfer, user=user)
        for reference, min_stock in {
            "DEMO-EAU-50": "15.000",
            "DEMO-JUS-OR": "8.000",
            "DEMO-SODA": "10.000",
        }.items():
            StockBalance.objects.filter(
                store=stores["mbr_south"],
                product=products[reference],
            ).update(min_stock=Decimal(min_stock))

    def _promotions(self, store, products, user):
        promotion, _ = Promotion.objects.update_or_create(
            store=store,
            name="Pack Fraicheur",
            defaults={
                "selling_price": Decimal("28.00"),
                "status": Promotion.Statuses.ACTIVE,
                "start_date": date.today(),
                "end_date": date.today() + timedelta(days=14),
                "created_by": user,
                "note": "Pack demo sans code barre.",
            },
        )
        promotion.lines.all().delete()
        PromotionLine.objects.create(
            promotion=promotion,
            product=products["DEMO-EAU-50"],
            quantity=Decimal("2.000"),
        )
        PromotionLine.objects.create(
            promotion=promotion,
            product=products["DEMO-JUS-OR"],
            quantity=Decimal("1.000"),
        )

    def _sales(self, store, products, user):
        create_sale(
            store=store,
            user=user,
            validated_data={
                "payment_mode_code": "cash",
                "lines": [
                    {
                        "product": products["DEMO-SODA"].pk,
                        "quantity": Decimal("2.000"),
                        "unit_price": Decimal("10.00"),
                    }
                ],
                "paid_amount": Decimal("20.00"),
                "idempotency_key": "DEMO-SALE-001",
            },
        )
        promotion = Promotion.objects.get(store=store, name="Pack Fraicheur")
        create_sale(
            store=store,
            user=user,
            validated_data={
                "payment_mode_code": "cash",
                "promotion_lines": [
                    {
                        "promotion": promotion.pk,
                        "quantity": Decimal("1.000"),
                        "unit_price": promotion.selling_price,
                    }
                ],
                "paid_amount": promotion.selling_price,
                "idempotency_key": "DEMO-SALE-PROMO-001",
            },
        )

    def _attendance(self, store):
        employee, _ = Employee.objects.update_or_create(
            store=store,
            full_name="Employe Demo",
            defaults={"position": "Vendeur", "is_active": True},
        )
        AttendanceRecord.objects.update_or_create(
            store=store,
            employee=employee,
            date=timezone.localdate(),
            defaults={
                "status": AttendanceRecord.Statuses.PRESENT,
                "clock_in": "09:00",
                "clock_out": "18:00",
                "hours_worked": Decimal("8.00"),
                "delay_minutes": 0,
            },
        )

    def _expenses(self, store):
        category, _ = ExpenseCategory.objects.update_or_create(
            code="demo-ops",
            defaults={"name": "Charges operations", "is_active": True},
        )
        Expense.objects.update_or_create(
            store=store,
            category=category,
            label="Charge demo",
            expense_date=timezone.localdate(),
            defaults={
                "amount": Decimal("120.00"),
                "payment_status": Expense.PaymentStatuses.PAID,
                "note": "Donnee demo",
            },
        )
