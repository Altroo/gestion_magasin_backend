import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from account.tasks import send_csv_example_email

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_send_csv_example_email_attaches_csv_and_excel():
    user = User.objects.create(
        first_name="Service",
        email="import_guide@example.com",
        password="1234",
    )

    send_csv_example_email.delay(user.pk, user.email)

    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert email.subject == "Guide d'importation des articles - E.B.H Gestion Magasin"
    assert "Guide d'importation des articles" in email.body
    assert len(email.attachments) == 2
    attachment_names = {attachment[0] for attachment in email.attachments}
    assert attachment_names == {"modele_articles.csv", "modele_articles.xlsx"}
    csv_attachment = next(
        attachment
        for attachment in email.attachments
        if attachment[0] == "modele_articles.csv"
    )
    assert "Réf;Désignation;Famille;Unité Vente" in csv_attachment[1]
