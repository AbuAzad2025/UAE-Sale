"""
🤖 AI Routes - Super Intelligent Assistant Endpoints
المساعد الذكي الخارق - Superhuman AI Assistant
"""
import os
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import csrf
from services.ai_service import AIService
from ai_knowledge.learning_system import learning_system
from ai_knowledge.global_knowledge import global_connector, expertise_updater
from ai_knowledge.self_improvement import self_improvement
from ai_knowledge.system_integration import system_integrator
from ai_knowledge.data_analyzer import data_analyzer
from ai_knowledge.knowledge_expansion import knowledge_expander
from ai_knowledge.document_generator import document_generator
from ai_knowledge.advanced_laws import advanced_laws
from ai_knowledge.automotive_ecu_knowledge import get_automotive_ecu_knowledge
from ai_knowledge.external_learning import get_external_learning, LEARNING_SOURCES_CATALOG
from utils.decorators import permission_required

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')

# Note: CSRF exemptions are added to individual routes that need them


@ai_bp.route('/recommend-price', methods=['POST'])
@csrf.exempt
@login_required
def recommend_price():
    """API: توصية السعر"""
    data = request.get_json()
    product_id = data.get('product_id')
    customer_id = data.get('customer_id')
    
    if not product_id or not customer_id:
        return jsonify({'error': 'Product and Customer required'}), 400
    
    recommendation = AIService.recommend_price(product_id, customer_id)
    
    if not recommendation:
        return jsonify({'error': 'Not found'}), 404
    
    return jsonify(recommendation)


@ai_bp.route('/check-stock', methods=['POST'])
@csrf.exempt
@login_required
def check_stock():
    """API: فحص المخزون"""
    data = request.get_json()
    product_id = data.get('product_id')
    quantity = data.get('quantity', 0)
    
    if not product_id:
        return jsonify({'error': 'Product required'}), 400
    
    alert = AIService.check_stock_alert(product_id, quantity)
    
    if alert:
        return jsonify(alert)
    
    return jsonify({'type': 'success', 'message': 'المخزون كافٍ'})


@ai_bp.route('/analyze-customer/<int:customer_id>', methods=['GET'])
@login_required
def analyze_customer(customer_id):
    """API: تحليل سلوك العميل"""
    analysis = AIService.analyze_customer_behavior(customer_id)
    
    if not analysis:
        return jsonify({'error': 'Customer not found'}), 404
    
    return jsonify(analysis)


@ai_bp.route('/exchange-rate/<currency>', methods=['GET'])
@login_required
def exchange_rate(currency):
    """API: اقتراح سعر الصرف"""
    suggestion = AIService.get_exchange_rate_suggestion(currency)
    return jsonify(suggestion)


@ai_bp.route('/search-market-price/<int:product_id>', methods=['GET'])
@login_required
def search_market_price(product_id):
    """API: البحث عن سعر القطعة في الأسواق العالمية"""
    from models import Product
    
    product = Product.query.get_or_404(product_id)
    
    # Placeholder response - feature not yet implemented
    return jsonify({
        'success': True,
        'product': product.name,
        'message': 'ميزة البحث العالمي قيد التطوير',
        'suggestions': []
    })


@ai_bp.route('/find-compatible/<int:product_id>', methods=['GET'])
@login_required
def find_compatible(product_id):
    """API: البحث عن السيارات المتوافقة"""
    from models import Product
    
    product = Product.query.get_or_404(product_id)
    
    # Placeholder response - feature not yet implemented
    return jsonify({
        'success': True,
        'product': product.name,
        'message': 'ميزة البحث عن المركبات المتوافقة قيد التطوير',
        'compatible_vehicles': []
    })


@ai_bp.route('/chat', methods=['POST'])
@csrf.exempt
@login_required
def chat():
    """API: الدردشة مع المساعد الذكي"""
    data = request.get_json()
    message = data.get('message', '').strip()
    context = data.get('context', {})
    
    # إضافة معلومات اللهجة ووضع المبتدئين
    if 'dialect' not in context:
        context['dialect'] = 'palestinian'
    if 'beginners_mode' not in context:
        context['beginners_mode'] = False
    
    # إضافة معلومات المستخدم للسياق
    context['current_user'] = current_user
    context['is_owner'] = current_user.is_owner if current_user else False
    
    if not message:
        return jsonify({'error': 'Message required'}), 400
    
    response = AIService.chat_response(message, context)
    
    return jsonify({
        'response': response,
        'ai_enabled': AIService.is_enabled(),
        'user_role': 'owner' if current_user.is_owner else 'user'
    })


@ai_bp.route('/assistant', methods=['GET'])
@login_required
def assistant_page():
    """صفحة المساعد الذكي"""
    return render_template('ai/assistant.html',
                         ai_enabled=AIService.is_enabled(),
                         current_user=current_user)


@ai_bp.route('/config', methods=['GET', 'POST'])
@login_required
@permission_required('manage_system')
def config():
    """إعدادات AI - تحديث المفاتيح يومياً"""
    if request.method == 'POST':
        api_key = request.form.get('api_key', '').strip()
        provider = request.form.get('provider', 'groq')
        
        if not api_key:
            return jsonify({'success': False, 'message': 'المفتاح مطلوب'})
        
        # حفظ المفتاح في ملف .env (دائم)
        try:
            import os
            from pathlib import Path
            
            env_file = Path('.env')
            
            # قراءة الملف الحالي
            if env_file.exists():
                with open(env_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            else:
                lines = []
            
            # تحديد اسم المتغير
            if provider == 'groq':
                key_name = 'GROQ_API_KEY'
            elif provider == 'gemini':
                key_name = 'GEMINI_API_KEY'
            else:
                key_name = 'OPENAI_API_KEY'
            
            key_found = False
            
            for i, line in enumerate(lines):
                if line.startswith(key_name + '='):
                    lines[i] = f'{key_name}={api_key}\n'
                    key_found = True
                    break
            
            if not key_found:
                lines.append(f'{key_name}={api_key}\n')
            
            # حفظ الملف
            with open(env_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            # تحديث البيئة الحالية
            os.environ[key_name] = api_key
            
            # تسجيل في اللوج
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"✅ {key_name} updated successfully by user {current_user.username}")
            
            return jsonify({
                'success': True, 
                'message': f'تم حفظ مفتاح {provider.upper()} بنجاح! ✅',
                'provider': provider,
                'expires_in': '24 ساعة' if provider == 'groq' else 'حسب اشتراكك'
            })
        
        except Exception as e:
            logger.error(f"Failed to save API key: {e}")
            return jsonify({'success': False, 'message': f'خطأ في الحفظ: {str(e)}'})
    
    # GET - عرض الصفحة مع المفاتيح الحالية
    current_groq = os.environ.get('GROQ_API_KEY', '')
    current_openai = os.environ.get('OPENAI_API_KEY', '')
    current_gemini = os.environ.get('GEMINI_API_KEY', '')
    
    return render_template('ai/config.html',
                         ai_enabled=AIService.is_enabled(),
                         groq_key_exists=bool(current_groq),
                         openai_key_exists=bool(current_openai or current_gemini),
                         groq_key_preview=current_groq[:20] + '...' if current_groq else '',
                         openai_key_preview=(current_openai or current_gemini)[:20] + '...' if (current_openai or current_gemini) else '')


# ========== Super AI Endpoints (القدرات الخارقة) ==========

@ai_bp.route('/predict-sales', methods=['GET'])
@login_required
def predict_sales():
    """🔮 API: توقع المبيعات"""
    days = request.args.get('days', 7, type=int)
    prediction = AIService.predict_sales_trend(days)
    return jsonify(prediction)


@ai_bp.route('/analyze-margins', methods=['GET'])
@login_required
def analyze_margins():
    """💰 API: تحليل هوامش الربح"""
    analysis = AIService.analyze_profit_margins()
    return jsonify(analysis)


@ai_bp.route('/detect-patterns', methods=['GET'])
@login_required
def detect_patterns():
    """🔍 API: كشف الأنماط"""
    patterns = AIService.detect_sales_patterns()
    return jsonify(patterns)


@ai_bp.route('/inventory-health', methods=['GET'])
@login_required
def inventory_health():
    """📦 API: صحة المخزون"""
    health = AIService.analyze_inventory_health()
    return jsonify(health)


@ai_bp.route('/deep-analysis', methods=['GET'])
@login_required
@permission_required('view_reports')
def deep_analysis():
    """📊 API: تحليل عميق شامل"""
    analysis = AIService.deep_business_analysis()
    return jsonify(analysis)


@ai_bp.route('/cash-flow-prediction', methods=['GET'])
@login_required
@permission_required('view_ledger')
def cash_flow_prediction():
    """💵 API: توقع التدفق النقدي"""
    days = request.args.get('days', 30, type=int)
    prediction = AIService.predict_cash_flow(days)
    return jsonify(prediction)


@ai_bp.route('/smart-price', methods=['POST'])
@login_required
def smart_price():
    """💎 API: محرك التسعير الذكي الخارق"""
    data = request.get_json()
    product_id = data.get('product_id')
    customer_id = data.get('customer_id')
    quantity = data.get('quantity', 1)
    
    if not product_id or not customer_id:
        return jsonify({'error': 'Product and Customer required'}), 400
    
    pricing = AIService.smart_pricing_engine(product_id, customer_id, quantity)
    
    if not pricing:
        return jsonify({'error': 'Not found'}), 404
    
    return jsonify(pricing)


@ai_bp.route('/churn-prediction', methods=['GET'])
@login_required
@permission_required('manage_customers')
def churn_prediction():
    """⚠️ API: توقع فقدان العملاء"""
    prediction = AIService.predict_customer_churn()
    return jsonify(prediction)


@ai_bp.route('/optimize-inventory', methods=['GET'])
@login_required
@permission_required('manage_warehouse')
def optimize_inventory():
    """📦 API: تحسين مستويات المخزون"""
    optimization = AIService.optimize_inventory_levels()
    return jsonify(optimization)


@ai_bp.route('/business-insights', methods=['GET'])
@login_required
def business_insights():
    """💡 API: رؤى الأعمال التلقائية"""
    insights = AIService.generate_business_insights()
    
    # تحويل الصيغة لتتوافق مع الواجهة
    formatted_insights = []
    for insight in insights:
        formatted_insights.append({
            'icon': '⚠️' if insight['type'] == 'warning' else 'ℹ️',
            'title': insight['title'],
            'insight': insight['message'],
            'action': insight['action']
        })
    
    return jsonify({
        'success': True,
        'insights': formatted_insights
    })


@ai_bp.route('/contextual-help/<page>', methods=['GET'])
@login_required
def contextual_help(page):
    """❓ API: مساعدة سياقية"""
    user_role = current_user.role.name if current_user.role else 'user'
    help_content = AIService.contextual_help(page, user_role)
    return jsonify(help_content)


# ==== نظام التعلم الذاتي والتحسين ====

@ai_bp.route('/learning/status')
@login_required
@permission_required('view_reports')
def learning_status():
    """حالة التعلم الذاتي"""
    try:
        insights = learning_system.get_learning_insights()
        return jsonify({
            'success': True,
            'learning_insights': insights
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/learning/evolve', methods=['POST'])
@login_required
@permission_required('admin')
def evolve_knowledge():
    """تطوير المعرفة تلقائياً"""
    try:
        evolution = learning_system.evolve_knowledge()
        return jsonify({
            'success': True,
            'evolution': evolution
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/improvement/status')
@login_required
@permission_required('view_reports')
def improvement_status():
    """حالة التحسين الذاتي"""
    try:
        status = self_improvement.get_improvement_status()
        return jsonify({
            'success': True,
            'improvement_status': status
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/improvement/auto-improve', methods=['POST'])
@login_required
@permission_required('admin')
def auto_improve():
    """التحسين التلقائي"""
    try:
        improvements = self_improvement.auto_improve()
        return jsonify({
            'success': True,
            'improvements': improvements
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/improvement/progress')
@login_required
@permission_required('view_reports')
def improvement_progress():
    """تتبع تقدم التحسين"""
    try:
        progress = self_improvement.track_progress()
        return jsonify({
            'success': True,
            'progress': progress
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/improvement/set-goal', methods=['POST'])
@login_required
@permission_required('admin')
def set_improvement_goal():
    """تعيين هدف تحسين"""
    try:
        data = request.get_json()
        area = data.get('area')
        target_score = data.get('target_score')
        timeframe = data.get('timeframe', '30_days')
        
        if not area or not target_score:
            return jsonify({
                'success': False,
                'error': 'المجال والهدف مطلوبان'
            }), 400
        
        result = self_improvement.set_improvement_goal(area, target_score, timeframe)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/global/insights')
@login_required
@permission_required('view_reports')
def global_insights():
    """رؤى عالمية"""
    try:
        insights = global_connector.get_global_insights()
        return jsonify({
            'success': True,
            'global_insights': insights
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/global/expertise-update')
@login_required
@permission_required('admin')
def update_global_expertise():
    """تحديث الخبرة العالمية"""
    try:
        updates = expertise_updater.update_expertise()
        return jsonify({
            'success': True,
            'expertise_updates': updates
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/performance/analysis')
@login_required
@permission_required('view_reports')
def performance_analysis():
    """تحليل الأداء الشامل"""
    try:
        # تحليل الأداء
        performance = self_improvement.analyze_performance()
        
        # رؤى التعلم
        learning_insights = learning_system.get_learning_insights()
        
        # التطور
        evolution = self_improvement.evolve_capabilities()
        
        # الرؤى العالمية
        global_insights = global_connector.get_global_insights()
        
        return jsonify({
            'success': True,
            'performance_analysis': {
                'performance': performance,
                'learning': learning_insights,
                'evolution': evolution,
                'global': global_insights
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==== تكامل النظام والبيانات الدقيقة ====

@ai_bp.route('/system/customer-balance/<customer_name>')
@login_required
@permission_required('view_customers')
def get_customer_balance(customer_name):
    """جلب رصيد العميل بدقة"""
    try:
        result = system_integrator.get_customer_balance(customer_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/system/customer-debt/<int:customer_id>')
@login_required
@permission_required('view_customers')
def analyze_customer_debt(customer_id):
    """تحليل ديون العميل بالتفصيل"""
    try:
        result = data_analyzer.analyze_customer_debt(customer_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/system/product-stock/<product_name>')
@login_required
@permission_required('view_products')
def get_product_stock(product_name):
    """جلب مخزون المنتج بدقة"""
    try:
        result = system_integrator.get_product_stock(product_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/system/summary')
@login_required
def get_system_summary():
    """ملخص النظام الشامل"""
    try:
        result = system_integrator.get_system_summary()
        financial_result = system_integrator.get_financial_summary()
        
        return jsonify({
            'success': True,
            'summary': result.get('summary', {}),
            'financial': financial_result.get('financial', {})
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/system/search/<search_term>')
@login_required
def search_system_data(search_term):
    """البحث في بيانات النظام"""
    try:
        result = system_integrator.search_data(search_term)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/system/add-customer', methods=['POST'])
@login_required
@permission_required('add_customers')
def add_customer():
    """إضافة عميل جديد"""
    try:
        data = request.get_json()
        result = system_integrator.add_customer(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/data/analyze-sales')
@login_required
@permission_required('view_reports')
def analyze_sales_performance():
    """تحليل أداء المبيعات"""
    try:
        period_days = request.args.get('period', 30, type=int)
        result = data_analyzer.analyze_sales_performance(period_days)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/data/analyze-products')
@login_required
@permission_required('view_products')
def analyze_product_performance():
    """تحليل أداء المنتجات"""
    try:
        product_id = request.args.get('product_id', type=int)
        result = data_analyzer.analyze_product_performance(product_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/data/financial-ratios')
@login_required
@permission_required('view_reports')
def get_financial_ratios():
    """النسب المالية"""
    try:
        result = data_analyzer.get_financial_ratios()
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==== توسيع المعرفة ====

@ai_bp.route('/knowledge/add-website', methods=['POST'])
@login_required
@permission_required('admin')
def add_knowledge_website():
    """إضافة موقع ويب للمعرفة"""
    try:
        data = request.get_json()
        url = data.get('url')
        category = data.get('category', 'general')
        description = data.get('description', '')
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'الرابط مطلوب'
            }), 400
        
        result = knowledge_expander.add_website(url, category, description)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/knowledge/add-document', methods=['POST'])
@login_required
@permission_required('admin')
def add_knowledge_document():
    """إضافة مستند للمعرفة"""
    try:
        data = request.get_json()
        content = data.get('content')
        title = data.get('title')
        category = data.get('category', 'general')
        description = data.get('description', '')
        
        if not content or not title:
            return jsonify({
                'success': False,
                'error': 'المحتوى والعنوان مطلوبان'
            }), 400
        
        result = knowledge_expander.add_document(content, title, category, description)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/knowledge/search')
@login_required
def search_knowledge():
    """البحث في المعرفة الموسعة"""
    try:
        query = request.args.get('q', '')
        category = request.args.get('category')
        
        if not query:
            return jsonify({
                'success': False,
                'error': 'كلمة البحث مطلوبة'
            }), 400
        
        result = knowledge_expander.search_knowledge(query, category)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ai_bp.route('/knowledge/summary')
@login_required
def get_knowledge_summary():
    """📚 API: ملخص المعرفة الموسعة"""
    try:
        result = knowledge_expander.get_knowledge_summary()
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# New Advanced Routes - المسارات المتقدمة الجديدة
# ============================================================================

@ai_bp.route('/neural-status', methods=['GET'])
@login_required
def neural_status():
    """🧠 API: حالة الشبكات العصبية"""
    try:
        status = AIService.get_neural_status()
        return jsonify({
            'success': True,
            'status': status
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@ai_bp.route('/automotive-ecu/<code>', methods=['GET'])
@login_required
def automotive_ecu_code(code):
    """🚗 API: تشخيص كود OBD-II"""
    try:
        ecu_expert = get_automotive_ecu_knowledge()
        diagnosis = ecu_expert.diagnose_code(code.upper())
        
        return jsonify({
            'success': True,
            'diagnosis': diagnosis
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@ai_bp.route('/automotive-sensor/<sensor>', methods=['GET'])
@login_required
def automotive_sensor(sensor):
    """🔧 API: معلومات حساس محدد"""
    try:
        ecu_expert = get_automotive_ecu_knowledge()
        info = ecu_expert.get_sensor_info(sensor)
        
        return jsonify({
            'success': True,
            'sensor_info': info
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@ai_bp.route('/external-sources', methods=['GET'])
@login_required
def external_sources():
    """📚 API: قائمة مصادر التعلم الخارجية"""
    try:
        learning = get_external_learning()
        sources = learning.get_knowledge_sources_list()
        stats = learning.get_statistics()
        
        return jsonify({
            'success': True,
            'sources': sources,
            'statistics': stats,
            'catalog': LEARNING_SOURCES_CATALOG
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@ai_bp.route('/ask-genius', methods=['POST'])
@csrf.exempt
@login_required
def ask_genius():
    """🌟 API: اسأل العبقري - الواجهة الموحدة"""
    try:
        data = request.get_json()
        question = data.get('question', '')
        context = data.get('context', {})
        
        if not question:
            return jsonify({
                'success': False,
                'error': 'السؤال مطلوب'
            }), 400
        
        # استخدام العقل الموحد
        result = AIService.ask_genius(
            question=question,
            context=context,
            user_id=current_user.id
        )
        
        return jsonify({
            'success': True,
            'result': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@ai_bp.route('/quick-calc', methods=['POST'])
@csrf.exempt
@login_required
def quick_calc():
    """⚡ API: حسابات سريعة"""
    try:
        data = request.get_json()
        formula = data.get('formula', '')
        params = data.get('params', {})
        
        if not formula:
            return jsonify({
                'success': False,
                'error': 'الصيغة مطلوبة'
            }), 400
        
        result = AIService.quick_calculate(formula, **params)
        
        return jsonify({
            'success': result.get('success', False),
            'result': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@ai_bp.route('/transformers-understand', methods=['POST'])
@csrf.exempt
@login_required
def transformers_understand():
    """🤖 API: فهم بالـ Transformers"""
    try:
        data = request.get_json()
        text = data.get('text', '')
        
        if not text:
            return jsonify({
                'success': False,
                'error': 'النص مطلوب'
            }), 400
        
        understanding = AIService.understand_with_transformers(text)
        
        return jsonify({
            'success': True,
            'understanding': understanding
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

