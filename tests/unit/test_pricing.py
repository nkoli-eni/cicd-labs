"""Tests unitaires des règles de prix — Atelier 1.

Couvre : arrondi, remise volume, quantités invalides, coupons (seuils inclus/exclus),
livraison, produit inconnu, et la nouvelle règle STUDENT15 (développée en TDD).

Prix du catalogue utilisés : mug 12.50 · tshirt 19.90 · sticker 2.45 · hoodie 44.00 · book 29.99
"""

from decimal import Decimal

import pytest

from minishop.pricing import coupon_discount, line_total, money, quote, shipping_cost

pytestmark = pytest.mark.unit


def D(value: str) -> Decimal:
    """Raccourci : construit un Decimal à partir d'une chaîne (jamais d'un float)."""
    return Decimal(value)


# --------------------------------------------------------------------------- rounding
def test_money_arrondi_commercial():
    """0.125 s'arrondit à 0.13 (ROUND_HALF_UP), pas 0.12."""
    assert money("0.125") == Decimal("0.13")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0.124", "0.12"),  # below the midpoint: rounds down
        ("0.125", "0.13"),  # exactly the midpoint: rounds up
        ("0.135", "0.14"),  # another midpoint case: rounds up
        ("2.985", "2.99"),  # half-even (Python default) would give 2.98
        ("130.625", "130.63"),  # half-even would give 130.62
    ],
)
def test_money_rounds_half_up(raw, expected):
    """Un montant exactement à la moitié d'un centime est arrondi vers le haut."""
    assert money(raw) == Decimal(expected)


# --------------------------------------------------------------------------- lines
def test_line_total_sans_remise():
    """Sous 10 unités, le total d'une ligne est prix x quantité, sans remise."""
    assert line_total(Decimal("12.50"), 2) == Decimal("25.00")


@pytest.mark.parametrize(
    "qty, expected",
    [
        (1, "12.50"),  # lowest valid quantity
        (9, "112.50"),  # 9 units: NO discount
        (10, "118.75"),  # 10 units: -5 % (125.00 x 0.95)
        (11, "130.63"),  # 137.50 x 0.95 = 130.625 -> rounded up
        (99, "1175.63"),  # highest valid quantity: 1237.50 x 0.95 = 1175.625
    ],
)
def test_line_total_volume_discount_at_boundaries(qty, expected):
    """La remise volume de 5 % démarre à 10 unités (et pas à 9)."""
    assert line_total(Decimal("12.50"), qty) == Decimal(expected)


@pytest.mark.parametrize("qty", [0, -1, 100, "2", True, 2.0, None])
def test_line_total_invalid_quantity(qty):
    """Une quantité hors de 1..99, ou qui n'est pas un entier (booléen compris), lève ValueError."""
    with pytest.raises(ValueError):
        line_total(Decimal("10"), qty)


# --------------------------------------------------------------------------- cart
def test_quote_panier_vide():
    """Un panier vide coûte 0 € : pas de frais de livraison."""
    q = quote([])
    assert q.total == Decimal("0.00")
    assert q.shipping == Decimal("0.00")


def test_quote_empty_cart_with_valid_coupon():
    """Un coupon sur un panier vide ne crée ni remise ni frais : le total reste à 0 €."""
    q = quote([], "WELCOME10")
    assert (q.discount, q.shipping, q.total) == (D("0.00"), D("0.00"), D("0.00"))


def test_quote_without_coupon_adds_shipping():
    """2 mugs sans coupon : 25.00 + 4.90 de livraison = 29.90."""
    q = quote([{"product_id": "mug", "qty": 2}])
    assert (q.subtotal, q.discount, q.shipping, q.total) == (D("25.00"), D("0.00"), D("4.90"), D("29.90"))


def test_quote_unknown_product():
    """Un produit absent du catalogue lève KeyError."""
    # match= uses the French message because the application itself raises it in French
    with pytest.raises(KeyError, match="Produit inconnu"):
        quote([{"product_id": "unicorn", "qty": 1}])


def test_quote_invalid_quantity_is_propagated():
    """Une quantité invalide dans le panier remonte en ValueError."""
    with pytest.raises(ValueError):
        quote([{"product_id": "mug", "qty": 0}])


def test_quote_as_dict_serialises_amounts_as_strings():
    """as_dict() renvoie les montants en chaînes, prêts pour le JSON de l'API."""
    d = quote([{"product_id": "mug", "qty": 2}], "welcome10").as_dict()
    assert d["lines"] == [{"product_id": "mug", "qty": 2, "unit_price": "12.50", "total": "25.00"}]
    assert (d["subtotal"], d["discount"], d["shipping"], d["total"], d["coupon"]) == (
        "25.00",
        "2.50",
        "4.90",
        "27.40",
        "WELCOME10",
    )


# --------------------------------------------------------------------------- coupons
@pytest.mark.parametrize(
    "subtotal, expected",
    [
        ("19.99", "0.00"),  # just under the threshold: no discount
        ("20.00", "2.00"),  # threshold included
        ("20.01", "2.00"),  # 2.001 -> 2.00
        ("25.00", "2.50"),
    ],
)
def test_coupon_welcome10_threshold_20_euros(subtotal, expected):
    """WELCOME10 : -10 % dès 20 € de sous-total (seuil inclus), rien en dessous."""
    assert coupon_discount(D(subtotal), "WELCOME10") == D(expected)


@pytest.mark.parametrize(
    "subtotal, expected",
    [
        ("29.99", "0.00"),  # just under the threshold
        ("30.00", "5.00"),  # threshold included
        ("100.00", "5.00"),  # fixed discount, independent of the amount
    ],
)
def test_coupon_fixed5_threshold_30_euros(subtotal, expected):
    """FIXED5 : -5 € fixes dès 30 € de sous-total (seuil inclus)."""
    assert coupon_discount(D(subtotal), "FIXED5") == D(expected)


def test_coupon_fixed5_below_threshold_in_a_cart():
    """Un livre à 29.99 € est sous le seuil de FIXED5 : pas de remise, la livraison est facturée."""
    q = quote([{"product_id": "book", "qty": 1}], "FIXED5")
    assert (q.discount, q.shipping, q.total) == (D("0.00"), D("4.90"), D("34.89"))


def test_coupon_freeship_removes_shipping():
    """FREESHIP ne change pas les prix mais supprime les frais de livraison."""
    q = quote([{"product_id": "mug", "qty": 1}], "FREESHIP")
    assert (q.discount, q.shipping, q.total) == (D("0.00"), D("0.00"), D("12.50"))


@pytest.mark.parametrize("code", ["BONJOUR", "WELCOME 10", "STUDENT50"])
def test_coupon_unknown(code):
    """Un coupon inconnu lève ValueError avec un message explicite."""
    # match= uses the French message because the application itself raises it in French
    with pytest.raises(ValueError, match="Coupon inconnu"):
        quote([{"product_id": "mug", "qty": 2}], code)


@pytest.mark.parametrize("coupon", [None, ""])
def test_coupon_absent_or_empty_has_no_effect(coupon):
    """Sans coupon (None ou chaîne vide) : aucune remise, et aucun coupon enregistré."""
    q = quote([{"product_id": "mug", "qty": 2}], coupon)
    assert q.discount == D("0.00")
    assert q.coupon is None


def test_coupon_ignores_case_and_spaces():
    """' welcome10 ' est reconnu comme WELCOME10 et normalisé dans le devis."""
    q = quote([{"product_id": "mug", "qty": 2}], " welcome10 ")
    assert q.coupon == "WELCOME10"
    assert q.discount == D("2.50")
    assert q.total == D("27.40")  # 25.00 - 2.50 + 4.90


# --------------------------------------------------------------------------- shipping
@pytest.mark.parametrize(
    "amount, expected",
    [
        ("49.99", "4.90"),  # just under the threshold: shipping is charged
        ("50.00", "0.00"),  # threshold included: free shipping
        ("120.00", "0.00"),
    ],
)
def test_shipping_free_from_50_euros(amount, expected):
    """Livraison à 4,90 €, offerte dès 50 € (seuil inclus)."""
    assert shipping_cost(D(amount), None, empty=False) == D(expected)


def test_shipping_threshold_is_checked_after_discount():
    """4 mugs = 50.00 € mais -10 % -> 45.00 € : sous le seuil, la livraison est facturée."""
    q = quote([{"product_id": "mug", "qty": 4}], "WELCOME10")
    assert (q.subtotal, q.discount, q.shipping, q.total) == (D("50.00"), D("5.00"), D("4.90"), D("49.90"))


def test_shipping_free_when_total_after_discount_reaches_50():
    """3 t-shirts = 59.70 € ; -10 % -> 53.73 € : livraison offerte."""
    q = quote([{"product_id": "tshirt", "qty": 3}], "WELCOME10")
    assert (q.discount, q.shipping, q.total) == (D("5.97"), D("0.00"), D("53.73"))


# --------------------------------------------------------------------------- STUDENT15 (TDD)
def test_student15_applies_15_percent_with_no_minimum():
    """STUDENT15 : -15 % sur un très petit panier, sans minimum (1 sticker = 2.45 €)."""
    q = quote([{"product_id": "sticker", "qty": 1}], "STUDENT15")
    assert (q.subtotal, q.discount, q.shipping, q.total) == (D("2.45"), D("0.37"), D("4.90"), D("6.98"))


def test_student15_applies_to_a_line_without_volume_discount():
    """STUDENT15 sur 2 mugs (pas de remise volume) : -15 % de 25.00 = 3.75."""
    q = quote([{"product_id": "mug", "qty": 2}], "STUDENT15")
    assert (q.subtotal, q.discount, q.shipping, q.total) == (D("25.00"), D("3.75"), D("4.90"), D("26.15"))


def test_student15_not_combinable_with_volume_discount():
    """10 mugs ont déjà -5 % : STUDENT15 n'ajoute aucune remise sur cette ligne."""
    q = quote([{"product_id": "mug", "qty": 10}], "STUDENT15")
    assert (q.subtotal, q.discount, q.shipping, q.total) == (D("118.75"), D("0.00"), D("0.00"), D("118.75"))


def test_student15_only_applies_to_lines_without_volume_discount():
    """Panier mixte : 10 mugs (remise volume) + 1 t-shirt : -15 % sur le t-shirt uniquement."""
    q = quote([{"product_id": "mug", "qty": 10}, {"product_id": "tshirt", "qty": 1}], "STUDENT15")
    assert q.subtotal == D("138.65")
    assert q.discount == D("2.99")  # 19.90 x 15 % = 2.985 -> 2.99 (rounded up)
    assert q.total == D("135.66")


def test_student15_ignores_case():
    """'student15' en minuscules est reconnu comme STUDENT15."""
    q = quote([{"product_id": "mug", "qty": 2}], "student15")
    assert q.coupon == "STUDENT15"
    assert q.discount == D("3.75")
    