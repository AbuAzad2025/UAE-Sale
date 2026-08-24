from flask import Blueprint, request, jsonify
from flask_login import login_required
from services.graphql_service import schema

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


@graphql_bp.route('', methods=['POST'])
@login_required
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
