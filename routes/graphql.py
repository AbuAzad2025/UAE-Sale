from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from services.graphql_service import schema
from utils.decorators import permission_required

graphql_bp = Blueprint('graphql', __name__, url_prefix='/graphql')

# SECURITY: Maximum allowed query depth to prevent DoS via deeply nested queries
MAX_QUERY_DEPTH = 10
# Maximum query string length
MAX_QUERY_LENGTH = 10000


def _estimate_query_depth(query_str):
    """Estimate GraphQL query depth by counting brace nesting."""
    depth = 0
    max_depth = 0
    for ch in query_str:
        if ch == '{':
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == '}':
            depth = max(0, depth - 1)
    return max_depth


def _extract_query_types(query_str):
    """Extract root field names from GraphQL query for permission mapping."""
    import re
    # Simple extraction of root fields (e.g., "sale", "sales", "customer", "customers", etc.)
    # Matches patterns like "sale(id: 1) {", "sales {", "customer {", etc.
    root_fields = re.findall(r'\b(\w+)\s*\([^)]*\)\s*\{', query_str)
    root_fields += re.findall(r'\b(\w+)\s*\{', query_str)
    return set(root_fields)


_GRAPHQL_PERMISSION_MAP = {
    'sale': 'manage_sales',
    'sales': 'manage_sales',
    'customer': 'manage_customers',
    'customers': 'manage_customers',
    'product': 'manage_products',
    'products': 'manage_products',
    'supplier': 'manage_suppliers',
    'suppliers': 'manage_suppliers',
    'purchase': 'manage_purchases',
    'purchases': 'manage_purchases',
    'payment': 'manage_payments',
    'payments': 'manage_payments',
    'receipt': 'manage_payments',
    'receipts': 'manage_payments',
    'cheque': 'manage_payments',
    'cheques': 'manage_payments',
    'expense': 'manage_expenses',
    'expenses': 'manage_expenses',
    'warehouse': 'manage_warehouse',
    'stockMovement': 'manage_warehouse',
    'stockMovements': 'manage_warehouse',
    'user': 'manage_users',
    'users': 'manage_users',
    'role': 'manage_users',
    'roles': 'manage_users',
    'auditLog': 'view_reports',
    'auditLogs': 'view_reports',
    'report': 'view_reports',
    'reports': 'view_reports',
    'ledger': 'view_ledger',
    'journalEntry': 'view_ledger',
    'journalEntries': 'view_ledger',
}


def _check_graphql_permissions(query_str):
    """Check if current user has required permissions for the GraphQL query fields."""
    if current_user.is_owner or current_user.is_super_admin():
        return None  # Owner/super_admin bypass all permission checks
    
    required_fields = _extract_query_types(query_str)
    missing_perms = []
    
    for field in required_fields:
        perm = _GRAPHQL_PERMISSION_MAP.get(field.lower())
        if perm and not current_user.has_permission(perm):
            missing_perms.append(f'{field} (requires {perm})')
    
    if missing_perms:
        return f'Insufficient permissions for GraphQL fields: {", ".join(missing_perms)}'
    return None


@graphql_bp.route('', methods=['POST'])
@login_required
@permission_required('view_reports')  # Base permission to access GraphQL at all
def graphql_query():
    data = request.get_json()
    if not data:
        return jsonify({'errors': ['Invalid JSON body']}), 400

    query = data.get('query', '')
    variables = data.get('variables')

    if not query:
        return jsonify({'errors': ['Query is required']}), 400

    # SECURITY: Enforce query length limit
    if len(query) > MAX_QUERY_LENGTH:
        return jsonify({'errors': [f'Query too long (max {MAX_QUERY_LENGTH} chars)']}), 400

    # SECURITY: Enforce query depth limit to prevent DoS
    depth = _estimate_query_depth(query)
    if depth > MAX_QUERY_DEPTH:
        return jsonify({'errors': [f'Query too deep (max depth {MAX_QUERY_DEPTH}, got {depth})']}), 400

    # SECURITY: Block introspection queries in production
    query_lower = query.lower().strip()
    if 'introspection' in query_lower or '__schema' in query_lower or '__type' in query_lower:
        return jsonify({'errors': ['Introspection is disabled']}), 403

    # SECURITY: Block all mutations — the GraphQL layer is read-only in
    # production. Cash/stock-affecting writes must go through the audited,
    # permission-checked REST routes (sales.create, payment_service, etc.),
    # which enforce double-entry + tenant invariants. The schema's
    # CreateSale mutation would otherwise let any view_reports user create
    # confirmed cross-tenant sales with hardcoded seller_id=1.
    if query_lower.startswith('mutation'):
        return jsonify({'errors': ['Mutations are not allowed via GraphQL']}), 403

    # SECURITY: Check field-level permissions
    perm_error = _check_graphql_permissions(query)
    if perm_error:
        return jsonify({'errors': [perm_error]}), 403

    result = schema.execute(query, variables=variables)

    response = {}
    if result.data:
        response['data'] = result.data
    if result.errors:
        # SECURITY: Don't leak internal error details
        response['errors'] = ['Query execution failed' if 'internal' in str(e).lower() else str(e) for e in result.errors]

    return jsonify(response)


@graphql_bp.route('/playground', methods=['GET'])
@login_required
@permission_required('view_reports')
def graphql_playground():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>GraphQL Playground</title>
        <meta charset="utf-8">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/graphql-playground-react/build/static/css/index.css" />
    </head>
    <body>
        <div id="root"></div>
        <script src="https://cdn.jsdelivr.net/npm/graphql-playground-react/build/static/js/middleware.js"></script>
        <script>
            window.addEventListener('load', function (event) {
                GraphQLPlayground.init(document.getElementById('root'), {
                    endpoint: '/graphql'
                })
            })
        </script>
    </body>
    </html>
    '''