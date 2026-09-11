import graphene
from flask_login import current_user
from models import Sale, Customer, Product
from extensions import db
from utils.decorators import get_owned_or_404


class SaleType(graphene.ObjectType):
    id = graphene.Int()
    sale_number = graphene.String()
    customer_id = graphene.Int()
    total_amount = graphene.Float()
    amount_base = graphene.Float()
    status = graphene.String()
    created_at = graphene.DateTime()


class CustomerType(graphene.ObjectType):
    id = graphene.Int()
    name = graphene.String()
    phone = graphene.String()
    email = graphene.String()
    address = graphene.String()
    balance = graphene.Float()


class ProductType(graphene.ObjectType):
    id = graphene.Int()
    name = graphene.String()
    part_number = graphene.String()
    regular_price = graphene.Float()
    cost_price = graphene.Float()
    current_stock = graphene.Int()
    is_active = graphene.Boolean()


class PaymentType(graphene.ObjectType):
    id = graphene.Int()
    amount = graphene.Float()
    currency = graphene.String()
    payment_method = graphene.String()
    reference_number = graphene.String()
    created_at = graphene.DateTime()


class Query(graphene.ObjectType):
    all_sales = graphene.List(SaleType, limit=graphene.Int(), offset=graphene.Int())
    sale = graphene.Field(SaleType, id=graphene.Int())

    all_customers = graphene.List(CustomerType, limit=graphene.Int())
    customer = graphene.Field(CustomerType, id=graphene.Int())

    all_products = graphene.List(ProductType, limit=graphene.Int())
    product = graphene.Field(ProductType, id=graphene.Int())

    def resolve_all_sales(self, info, limit=50, offset=0):
        sales = _scoped_list_query(Sale).limit(limit).offset(offset).all()
        return [_convert_sale_to_type(sale) for sale in sales]

    def resolve_sale(self, info, id):
        sale = get_owned_or_404(Sale, id, code=404)
        return _convert_sale_to_type(sale)

    def resolve_all_customers(self, info, limit=50):
        customers = _scoped_list_query(Customer).limit(limit).all()
        return [_convert_customer_to_type(customer) for customer in customers]

    def resolve_customer(self, info, id):
        customer = get_owned_or_404(Customer, id, code=404)
        return _convert_customer_to_type(customer)

    def resolve_all_products(self, info, limit=50):
        products = _scoped_list_query(Product).limit(limit).all()
        return [_convert_product_to_type(product) for product in products]

    def resolve_product(self, info, id):
        product = get_owned_or_404(Product, id, code=404)
        return _convert_product_to_type(product)


def _scoped_list_query(model):
    """Explicit tenant scoping for list resolvers.

    Mirrors the single-item resolvers' get_owned_or_404 enforcement
    (utils.decorators._enforce_same_tenant): owner / super_admin and
    anonymous contexts see everything; a tenant-scoped user only sees rows
    in their own tenant. Tenant-less rows are invisible to scoped users
    (fail closed), exactly like the single-item 403 path.
    """
    query = model.query
    try:
        if not getattr(current_user, 'is_authenticated', False):
            return query
        if getattr(current_user, 'is_owner', False):
            return query
        _is_super_admin = getattr(current_user, 'is_super_admin', None)
        if callable(_is_super_admin):
            try:
                if _is_super_admin():
                    return query
            except Exception:
                pass
        actor_tenant = getattr(current_user, 'tenant_id', None)
        if actor_tenant is None:
            return query
        return query.filter(model.tenant_id == actor_tenant)
    except Exception:
        return query


def _convert_sale_to_type(sale):
    return SaleType(
        id=sale.id,
        sale_number=sale.sale_number,
        customer_id=sale.customer_id,
        total_amount=float(sale.total_amount) if sale.total_amount else 0,
        amount_base=float(sale.amount_base) if sale.amount_base else 0,
        status=sale.status,
        created_at=sale.created_at
    )


def _convert_customer_to_type(customer):
    return CustomerType(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        email=customer.email,
        address=customer.address,
        balance=float(customer.balance) if customer.balance else 0
    )


def _convert_product_to_type(product):
    # SECURITY: cost_price is financial data — mask it for roles without
    # cost visibility (seller/inventory pass the manage_products field
    # check but must never read cost via GraphQL).
    show_cost = bool(getattr(current_user, 'is_authenticated', False)) \
        and current_user.can_see_costs()
    return ProductType(
        id=product.id,
        name=product.name,
        part_number=product.part_number,
        regular_price=float(product.regular_price) if product.regular_price else 0,
        cost_price=(float(product.cost_price) if product.cost_price else 0)
                   if show_cost else None,
        current_stock=product.current_stock,
        is_active=product.is_active
    )


class CreateSale(graphene.Mutation):
    class Arguments:
        customer_id = graphene.Int(required=True)
        total_amount = graphene.Float(required=True)

    sale = graphene.Field(SaleType)
    success = graphene.Boolean()

    def mutate(self, info, customer_id, total_amount):
        from utils.helpers import generate_number
        from decimal import Decimal

        sale = Sale(
            sale_number=generate_number('INV', Sale, 'sale_number'),
            customer_id=customer_id,
            seller_id=1,
            total_amount=Decimal(str(total_amount)),
            amount_base=Decimal(str(total_amount)),
            status='confirmed'
        )
        db.session.add(sale)
        db.session.commit()

        # Convert to SaleType
        sale_type = SaleType(
            id=sale.id,
            sale_number=sale.sale_number,
            customer_id=sale.customer_id,
            total_amount=float(sale.total_amount),
            amount_base=float(sale.amount_base),
            status=sale.status,
            created_at=sale.created_at
        )

        return CreateSale(sale=sale_type, success=True)


class Mutation(graphene.ObjectType):
    create_sale = CreateSale.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
