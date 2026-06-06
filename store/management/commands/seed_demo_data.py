from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from attendance.models import AttendanceRecord, Employee
from catalog.models import Category, Product, ProductUnit
from finance.models import Expense, ExpenseCategory
from sales.models import Customer, PaymentMode, Promotion, PromotionLine
from sales.services import create_sale
from stock.models import (
    InventoryLine,
    InventorySession,
    Purchase,
    PurchaseLine,
    StockBalance,
    StockTransfer,
    StockTransferLine,
)
from stock.services import receive_purchase, validate_inventory_session, validate_stock_transfer
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
            self._purchases(stores, products, users["admin"])
            self._transfers(stores, products, users["admin"])
            self._ensure_store_stock(stores, products)
            self._promotions(stores, products, users["seller"])
            self._customers(stores)
            self._sales(stores, products, users["seller"])
            self._attendance(stores)
            self._expenses(stores)
            self._inventory(stores, products, users["admin"])
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
        casablanca, _ = Store.objects.update_or_create(
            code="magasin-casablanca",
            defaults={
                "name": "Magasin Casablanca",
                "address": "Casablanca",
                "phone": "0522000000",
                "is_active": True,
                "is_global_stock": False,
            },
        )
        rabat, _ = Store.objects.update_or_create(
            code="magasin-rabat",
            defaults={
                "name": "Magasin Rabat",
                "address": "Rabat",
                "phone": "0537000000",
                "is_active": True,
                "is_global_stock": False,
            },
        )
        tanger, _ = Store.objects.update_or_create(
            code="magasin-tanger",
            defaults={
                "name": "Magasin Tanger",
                "address": "Tanger",
                "phone": "0539000000",
                "is_active": True,
                "is_global_stock": False,
            },
        )
        Store.objects.filter(code="mbr-demo").update(is_active=False)
        return {"mbr_stock": mbr_stock, "casablanca": casablanca, "rabat": rabat, "tanger": tanger}

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
        for store in [stores["casablanca"], stores["rabat"], stores["tanger"]]:
            StoreMembership.objects.update_or_create(
                user=seller,
                store=store,
                defaults={"role": roles[Role.Codes.RESPONSABLE], "is_active": True},
            )
        return {"admin": admin, "seller": seller}

    def _products(self):
        drinks, _ = Category.objects.update_or_create(
            code="demo-boisson",
            defaults={"name": "Boissons", "is_active": True},
        )
        groceries, _ = Category.objects.update_or_create(
            code="demo-epicerie",
            defaults={"name": "Epicerie", "is_active": True},
        )
        hygiene, _ = Category.objects.update_or_create(
            code="demo-hygiene",
            defaults={"name": "Hygiene", "is_active": True},
        )
        unit, _ = ProductUnit.objects.update_or_create(
            code="unite",
            defaults={"name": "Unité", "is_active": True},
        )
        product_specs = [
            ("DEMO-EAU-50", "6111000000011", "Eau minerale 50cl", drinks, "3.50", "6.00", "25.000"),
            ("DEMO-JUS-OR", "6111000000028", "Jus orange 1L", drinks, "9.00", "16.00", "12.000"),
            ("DEMO-SODA", "6111000000035", "Soda canette", drinks, "5.00", "10.00", "18.000"),
            ("DEMO-LAIT", "6111000000042", "Lait UHT 1L", groceries, "6.80", "11.00", "20.000"),
            ("DEMO-SUCRE", "6111000000059", "Sucre 1kg", groceries, "8.50", "13.00", "18.000"),
            ("DEMO-THE", "6111000000066", "The vert 200g", groceries, "17.00", "29.00", "8.000"),
            ("DEMO-SAVON", "6111000000073", "Savon liquide 500ml", hygiene, "12.00", "22.00", "10.000"),
            ("DEMO-MOUCHOIRS", "6111000000080", "Mouchoirs boite", hygiene, "7.50", "14.00", "12.000"),
        ]
        products = {}
        for reference, barcode, name, category, purchase_price, counter_price, alert in product_specs:
            product, _ = Product.objects.update_or_create(
                reference=reference,
                defaults={
                    "barcode": barcode,
                    "name": name,
                    "category": category,
                    "unit": unit,
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
            "DEMO-LAIT": ("160.000", "25.000"),
            "DEMO-SUCRE": ("140.000", "20.000"),
            "DEMO-THE": ("80.000", "10.000"),
            "DEMO-SAVON": ("90.000", "12.000"),
            "DEMO-MOUCHOIRS": ("110.000", "15.000"),
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

    def _purchases(self, stores, products, user):
        purchase_specs = [
            ("DEMO-ACH-001", stores["casablanca"], "Distributeur Casa", 7, {"DEMO-LAIT": ("36.000", "6.60"), "DEMO-SUCRE": ("24.000", "8.30")}),
            ("DEMO-ACH-002", stores["rabat"], "Grossiste Rabat", 5, {"DEMO-SAVON": ("18.000", "11.50"), "DEMO-MOUCHOIRS": ("30.000", "7.20")}),
            ("DEMO-ACH-003", stores["tanger"], "Central Nord", 3, {"DEMO-THE": ("12.000", "16.50"), "DEMO-EAU-50": ("48.000", "3.40")}),
        ]
        for reference, store, supplier, days_ago, lines in purchase_specs:
            if Purchase.objects.filter(reference=reference).exists():
                continue
            purchase = Purchase.objects.create(
                store=store,
                supplier_name=supplier,
                reference=reference,
                purchase_date=timezone.localdate() - timedelta(days=days_ago),
                status=Purchase.Statuses.DRAFT,
                created_by=user,
                note="Achat demo magasin",
            )
            subtotal = Decimal("0")
            for product_ref, (quantity, unit_cost) in lines.items():
                line = PurchaseLine.objects.create(
                    purchase=purchase,
                    product=products[product_ref],
                    quantity=Decimal(quantity),
                    unit_cost=Decimal(unit_cost),
                )
                subtotal += line.total
            purchase.subtotal = subtotal
            purchase.save(update_fields=["subtotal"])
            receive_purchase(purchase=purchase, user=user)

    def _transfers(self, stores, products, user):
        transfer_specs = [
            ("DEMO-TR-001", stores["casablanca"], 10, {"DEMO-EAU-50": "60.000", "DEMO-JUS-OR": "35.000", "DEMO-SODA": "45.000"}),
            ("DEMO-TR-002", stores["rabat"], 8, {"DEMO-EAU-50": "42.000", "DEMO-LAIT": "30.000", "DEMO-SUCRE": "26.000"}),
            ("DEMO-TR-003", stores["tanger"], 6, {"DEMO-SODA": "36.000", "DEMO-THE": "14.000", "DEMO-MOUCHOIRS": "28.000"}),
        ]
        for reference, target_store, days_ago, lines in transfer_specs:
            if StockTransfer.objects.filter(reference=reference).exists():
                continue
            transfer = StockTransfer.objects.create(
                target_store=target_store,
                reference=reference,
                transfer_date=timezone.localdate() - timedelta(days=days_ago),
                status=StockTransfer.Statuses.DRAFT,
                created_by=user,
                note="Dotation initiale demo",
            )
            for product_ref, quantity in lines.items():
                StockTransferLine.objects.create(
                    transfer=transfer,
                    product=products[product_ref],
                    quantity=Decimal(quantity),
                )
            validate_stock_transfer(transfer=transfer, user=user)
        for store_key in ["casablanca", "rabat", "tanger"]:
            for reference, min_stock in {
                "DEMO-EAU-50": "15.000",
                "DEMO-JUS-OR": "8.000",
                "DEMO-SODA": "10.000",
                "DEMO-LAIT": "12.000",
                "DEMO-SUCRE": "10.000",
                "DEMO-THE": "6.000",
                "DEMO-SAVON": "8.000",
                "DEMO-MOUCHOIRS": "8.000",
            }.items():
                StockBalance.objects.filter(
                    store=stores[store_key],
                    product=products[reference],
                ).update(min_stock=Decimal(min_stock))

    def _ensure_store_stock(self, stores, products):
        desired_quantities = {
            "casablanca": {
                "DEMO-EAU-50": "90.000",
                "DEMO-JUS-OR": "45.000",
                "DEMO-SODA": "55.000",
                "DEMO-LAIT": "38.000",
                "DEMO-SUCRE": "32.000",
                "DEMO-THE": "16.000",
                "DEMO-SAVON": "18.000",
                "DEMO-MOUCHOIRS": "28.000",
            },
            "rabat": {
                "DEMO-EAU-50": "54.000",
                "DEMO-JUS-OR": "18.000",
                "DEMO-SODA": "22.000",
                "DEMO-LAIT": "35.000",
                "DEMO-SUCRE": "38.000",
                "DEMO-THE": "14.000",
                "DEMO-SAVON": "24.000",
                "DEMO-MOUCHOIRS": "35.000",
            },
            "tanger": {
                "DEMO-EAU-50": "60.000",
                "DEMO-JUS-OR": "16.000",
                "DEMO-SODA": "40.000",
                "DEMO-LAIT": "20.000",
                "DEMO-SUCRE": "18.000",
                "DEMO-THE": "20.000",
                "DEMO-SAVON": "14.000",
                "DEMO-MOUCHOIRS": "42.000",
            },
        }
        min_stocks = {
            "DEMO-EAU-50": "15.000",
            "DEMO-JUS-OR": "8.000",
            "DEMO-SODA": "10.000",
            "DEMO-LAIT": "12.000",
            "DEMO-SUCRE": "10.000",
            "DEMO-THE": "6.000",
            "DEMO-SAVON": "8.000",
            "DEMO-MOUCHOIRS": "8.000",
        }
        for store_key, quantities in desired_quantities.items():
            store = stores[store_key]
            for reference, quantity in quantities.items():
                product = products[reference]
                balance, _ = StockBalance.objects.get_or_create(
                    store=store,
                    product=product,
                    defaults={
                        "quantity": Decimal("0"),
                        "min_stock": Decimal(min_stocks[reference]),
                        "average_cost": product.purchase_price,
                    },
                )
                target_quantity = Decimal(quantity)
                update_fields = []
                if balance.quantity < target_quantity:
                    balance.quantity = target_quantity
                    update_fields.append("quantity")
                if balance.min_stock is None:
                    balance.min_stock = Decimal(min_stocks[reference])
                    update_fields.append("min_stock")
                if balance.average_cost != product.purchase_price:
                    balance.average_cost = product.purchase_price
                    update_fields.append("average_cost")
                if update_fields:
                    update_fields.append("date_updated")
                    balance.save(update_fields=update_fields)

    def _promotions(self, stores, products, user):
        store = stores["casablanca"]
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
        promo_rabat, _ = Promotion.objects.update_or_create(
            store=stores["rabat"],
            name="Pack Maison",
            defaults={
                "selling_price": Decimal("45.00"),
                "status": Promotion.Statuses.ACTIVE,
                "start_date": date.today() - timedelta(days=3),
                "end_date": date.today() + timedelta(days=20),
                "created_by": user,
                "note": "Pack demo epicerie.",
            },
        )
        promo_rabat.lines.all().delete()
        PromotionLine.objects.create(promotion=promo_rabat, product=products["DEMO-SUCRE"], quantity=Decimal("2.000"))
        PromotionLine.objects.create(promotion=promo_rabat, product=products["DEMO-THE"], quantity=Decimal("1.000"))

    def _customers(self, stores):
        for store, customer_names in {
            stores["casablanca"]: ["Client Comptoir Casa", "Restaurant Atlas"],
            stores["rabat"]: ["Client Rabat Centre", "Cafe Agdal"],
            stores["tanger"]: ["Hotel Nord", "Client Tanger Medina"],
        }.items():
            for name in customer_names:
                Customer.objects.update_or_create(
                    store=store,
                    full_name=name,
                    defaults={"phone": "0600000000", "credit_limit": Decimal("1000.00"), "is_active": True},
                )

    def _set_sale_date(self, sale, days_ago):
        sale.date_created = timezone.now() - timedelta(days=days_ago)
        sale.save(update_fields=["date_created"])

    def _sales(self, stores, products, user):
        sale = create_sale(
            store=stores["casablanca"],
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
        self._set_sale_date(sale, 4)
        promotion = Promotion.objects.get(store=stores["casablanca"], name="Pack Fraicheur")
        sale = create_sale(
            store=stores["casablanca"],
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
        self._set_sale_date(sale, 2)
        sale_specs = [
            ("DEMO-SALE-002", stores["casablanca"], 1, [{"product": products["DEMO-LAIT"].pk, "quantity": Decimal("3.000"), "unit_price": Decimal("11.00")}]),
            ("DEMO-SALE-003", stores["rabat"], 6, [{"product": products["DEMO-SUCRE"].pk, "quantity": Decimal("2.000"), "unit_price": Decimal("13.00")}]),
            ("DEMO-SALE-004", stores["rabat"], 3, [{"product": products["DEMO-SAVON"].pk, "quantity": Decimal("1.000"), "unit_price": Decimal("22.00")}]),
            ("DEMO-SALE-005", stores["tanger"], 5, [{"product": products["DEMO-THE"].pk, "quantity": Decimal("1.000"), "unit_price": Decimal("29.00")}]),
            ("DEMO-SALE-006", stores["tanger"], 1, [{"product": products["DEMO-MOUCHOIRS"].pk, "quantity": Decimal("4.000"), "unit_price": Decimal("14.00")}]),
        ]
        for key, store, days_ago, lines in sale_specs:
            sale = create_sale(
                store=store,
                user=user,
                validated_data={
                    "payment_mode_code": "cash",
                    "lines": lines,
                    "paid_amount": sum(line["quantity"] * line["unit_price"] for line in lines),
                    "idempotency_key": key,
                },
            )
            self._set_sale_date(sale, days_ago)

    def _attendance(self, stores):
        for store in [stores["casablanca"], stores["rabat"], stores["tanger"]]:
            for index, name in enumerate(["Employe Demo", "Caissier Demo"]):
                employee, _ = Employee.objects.update_or_create(
                    store=store,
                    full_name=f"{name} {store.name.split()[-1]}",
                    defaults={"position": "Vendeur" if index == 0 else "Caissier", "is_active": True},
                )
                for days_ago in range(0, 5):
                    AttendanceRecord.objects.update_or_create(
                        store=store,
                        employee=employee,
                        date=timezone.localdate() - timedelta(days=days_ago),
                        defaults={
                            "status": AttendanceRecord.Statuses.PRESENT if days_ago != 3 else AttendanceRecord.Statuses.OFF,
                            "clock_in": "09:00",
                            "clock_out": "18:00",
                            "hours_worked": Decimal("8.00") if days_ago != 3 else Decimal("0.00"),
                            "delay_minutes": 5 if days_ago == 1 and index == 1 else 0,
                            "responsible": "Service IT",
                        },
                    )

    def _expenses(self, stores):
        category, _ = ExpenseCategory.objects.update_or_create(
            code="demo-ops",
            defaults={"name": "Charges operations", "is_active": True},
        )
        rent, _ = ExpenseCategory.objects.update_or_create(
            code="demo-loyer",
            defaults={"name": "Loyer et charges", "is_active": True},
        )
        specs = [
            (stores["casablanca"], category, "Fournitures caisse", "120.00", 2),
            (stores["casablanca"], rent, "Charge local", "850.00", 7),
            (stores["rabat"], category, "Transport marchandises", "210.00", 4),
            (stores["rabat"], rent, "Electricite", "340.00", 8),
            (stores["tanger"], category, "Petite maintenance", "180.00", 3),
            (stores["tanger"], rent, "Internet magasin", "250.00", 6),
        ]
        for store, expense_category, label, amount, days_ago in specs:
            Expense.objects.update_or_create(
                store=store,
                category=expense_category,
                label=label,
                expense_date=timezone.localdate() - timedelta(days=days_ago),
                defaults={
                    "amount": Decimal(amount),
                    "payment_status": Expense.PaymentStatuses.PAID,
                    "payment_mode": Expense.PaymentModes.CASH,
                    "note": "Donnee demo",
                },
            )

    def _inventory(self, stores, products, user):
        for store_key, store in [("casablanca", stores["casablanca"]), ("rabat", stores["rabat"]), ("tanger", stores["tanger"])]:
            code = f"DEMO-INV-{store_key.upper()}"
            session, created = InventorySession.objects.update_or_create(
                store=store,
                code=code,
                defaults={
                    "title": f"Inventaire demo {store.name}",
                    "inventory_date": timezone.localdate() - timedelta(days=1),
                    "status": InventorySession.Statuses.DRAFT,
                    "created_by": user,
                    "note": "Controle demo",
                },
            )
            if not created and session.status == InventorySession.Statuses.VALIDATED:
                continue
            session.lines.all().delete()
            for product in list(products.values())[:5]:
                balance = StockBalance.objects.filter(store=store, product=product).first()
                expected = balance.quantity if balance else Decimal("0")
                InventoryLine.objects.create(
                    session=session,
                    product=product,
                    expected_quantity=expected,
                    counted_quantity=expected,
                    note="OK",
                )
            validate_inventory_session(session=session, user=user)
