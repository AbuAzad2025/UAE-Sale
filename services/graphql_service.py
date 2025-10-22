import graphene
from graphene_sqlalchemy import SQLAlchemyObjectType
from models import Sale, Customer, Product, Payment
from extensions import db


class SaleType(SQLAlchemyObjectType):
    class Meta:
        model = Sale
        exclude_fields = []


class CustomerType(SQLAlchemyObjectType):
    class Meta:
        model = Customer
        exclude_fields = []


class ProductType(SQLAlchemyObjectType):
    class Meta:
        model = Product
        exclude_fields = []


class PaymentType(SQLAlchemyObjectType):
    class Meta:
        model = Payment
        exclude_fields = []


class Query(graphene.ObjectType):
    all_sales = graphene.List(SaleType, limit=graphene.Int(), offset=graphene.Int())
    sale = graphene.Field(SaleType, id=graphene.Int())
    
    all_customers = graphene.List(CustomerType, limit=graphene.Int())
    customer = graphene.Field(CustomerType, id=graphene.Int())
    
    all_products = graphene.List(ProductType, limit=graphene.Int())
    product = graphene.Field(ProductType, id=graphene.Int())
    
    def resolve_all_sales(self, info, limit=50, offset=0):
        return Sale.query.limit(limit).offset(offset).all()
    
    def resolve_sale(self, info, id):
        return Sale.query.get(id)
    
    def resolve_all_customers(self, info, limit=50):
        return Customer.query.limit(limit).all()
    
    def resolve_customer(self, info, id):
        return Customer.query.get(id)
    
    def resolve_all_products(self, info, limit=50):
        return Product.query.limit(limit).all()
    
    def resolve_product(self, info, id):
        return Product.query.get(id)


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
            amount_aed=Decimal(str(total_amount)),
            status='confirmed'
        )
        db.session.add(sale)
        db.session.commit()
        
        return CreateSale(sale=sale, success=True)


class Mutation(graphene.ObjectType):
    create_sale = CreateSale.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)

