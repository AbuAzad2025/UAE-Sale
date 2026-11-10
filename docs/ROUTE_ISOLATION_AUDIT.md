# Route Isolation Audit — 516 مسارًا

**توليد:** `scripts/gen_route_audit_doc.py` — لا يُعدَّل يدويًا؛ أي تغيير يُعاد توليد
الفحص عبر التشغيل: `python -m scripts.gen_route_audit_doc` والالتزام بها في كل
دفعة يمر بها CI (tests/unit/test_route_isolation_census.py يرفض أي مسار جديد
غير مصنَّف أو أي مسار tenant بدون رمز عزل).

**المعنى:**

* `public` — لا بيانات مستأجر (صفحة تسويق/دعم/توثيق) — يمكن أن تكون مفتوحة
* `system` — نقاط فحص ورصد (health/version/metrics) — لا بيانات أيضًا
* `platform` — لوحة المالك / بيع باقات المنصة — `is_owner` أو فوقها
* `tenant` — بيانات الشركة حصرًا ويجب أن يحمل رمز تمرير عزل واحدًا على
  الأقل (get_owned_or_404 أو tenant_id أو ما يكافئها)

**التنفيذ:** المسار `tenant` في حال عدم المطابقة يمنع POST/GET بدون `is_owner`،
وهو شرط CI صارم (route_isolation_census).

## routes.advanced_ledger (tenant) — 18 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/ledger/advanced/advanced-analytics` | `advanced_ledger.advanced_analytics` | tenant | login_required |
| `/ledger/advanced/advanced-expenses` | `advanced_ledger.advanced_expenses` | tenant | permission_required, login_required |
| `/ledger/advanced/advanced-expenses/add` | `advanced_ledger.add_advanced_expense` | tenant | login_required |
| `/ledger/advanced/api/cheque/<int:cheque_id>/accounting-summary` | `advanced_ledger.cheque_accounting_summary_api` | tenant | permission_required, login_required |
| `/ledger/advanced/api/events/stream` | `advanced_ledger.events_stream_api` | tenant | login_required |
| `/ledger/advanced/api/financial-ratios` | `advanced_ledger.api_financial_ratios` | tenant | permission_required, login_required |
| `/ledger/advanced/api/forecasting` | `advanced_ledger.api_forecasting` | tenant | login_required |
| `/ledger/advanced/api/trend-analysis` | `advanced_ledger.api_trend_analysis` | tenant | permission_required, login_required |
| `/ledger/advanced/cheque-integration` | `advanced_ledger.cheque_integration` | tenant | permission_required, login_required |
| `/ledger/advanced/cheque-integration/<int:cheque_id>/clear` | `advanced_ledger.clear_cheque` | tenant | login_required |
| `/ledger/advanced/cheque-integration/<int:cheque_id>/receive` | `advanced_ledger.receive_cheque` | tenant | login_required |
| `/ledger/advanced/customs-taxes` | `advanced_ledger.customs_taxes` | tenant | login_required |
| `/ledger/advanced/customs-taxes/add` | `advanced_ledger.add_customs_tax` | tenant | login_required |
| `/ledger/advanced/expense-categories` | `advanced_ledger.expense_categories` | tenant | login_required |
| `/ledger/advanced/expense-categories/add` | `advanced_ledger.add_expense_category` | tenant | login_required |
| `/ledger/advanced/professional-printing` | `advanced_ledger.professional_printing` | tenant | permission_required, login_required |
| `/ledger/advanced/professional-reports` | `advanced_ledger.professional_reports` | tenant | permission_required, login_required |
| `/ledger/advanced/real-time-events` | `advanced_ledger.real_time_events` | tenant | login_required |

## routes.ai (tenant) — 51 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/ai/analyze-customer/<int:customer_id>` | `ai.analyze_customer` | tenant | login_required |
| `/ai/analyze-margins` | `ai.analyze_margins` | tenant | login_required |
| `/ai/ask-genius` | `ai.ask_genius` | tenant | login_required |
| `/ai/assistant` | `ai.assistant_page` | tenant | owner_required, login_required |
| `/ai/automotive-ecu/<code>` | `ai.automotive_ecu_code` | tenant | login_required |
| `/ai/automotive-sensor/<sensor>` | `ai.automotive_sensor` | tenant | login_required |
| `/ai/business-insights` | `ai.business_insights` | tenant | login_required |
| `/ai/cash-flow-prediction` | `ai.cash_flow_prediction` | tenant | permission_required, login_required |
| `/ai/chat` | `ai.chat` | tenant | login_required |
| `/ai/check-stock` | `ai.check_stock` | tenant | login_required |
| `/ai/churn-prediction` | `ai.churn_prediction` | tenant | permission_required, login_required |
| `/ai/config` | `ai.config` | tenant | owner_required, login_required |
| `/ai/contextual-help/<page>` | `ai.contextual_help` | tenant | login_required |
| `/ai/data/analyze-products` | `ai.analyze_product_performance` | tenant | permission_required, login_required |
| `/ai/data/analyze-sales` | `ai.analyze_sales_performance` | tenant | permission_required, login_required |
| `/ai/data/financial-ratios` | `ai.get_financial_ratios` | tenant | permission_required, login_required |
| `/ai/deep-analysis` | `ai.deep_analysis` | tenant | permission_required, login_required |
| `/ai/detect-patterns` | `ai.detect_patterns` | tenant | login_required |
| `/ai/exchange-rate/<currency>` | `ai.exchange_rate` | tenant | login_required |
| `/ai/external-sources` | `ai.external_sources` | tenant | login_required |
| `/ai/find-compatible/<int:product_id>` | `ai.find_compatible` | tenant | get_owned_or_404, login_required |
| `/ai/global/expertise-update` | `ai.update_global_expertise` | tenant | login_required |
| `/ai/global/insights` | `ai.global_insights` | tenant | permission_required, login_required |
| `/ai/guide` | `ai.guide_api` | tenant | scope, login_required |
| `/ai/improvement/auto-improve` | `ai.auto_improve` | tenant | login_required |
| `/ai/improvement/progress` | `ai.improvement_progress` | tenant | permission_required, login_required |
| `/ai/improvement/set-goal` | `ai.set_improvement_goal` | tenant | login_required |
| `/ai/improvement/status` | `ai.improvement_status` | tenant | permission_required, login_required |
| `/ai/inventory-health` | `ai.inventory_health` | tenant | login_required |
| `/ai/knowledge/add-document` | `ai.add_knowledge_document` | tenant | login_required |
| `/ai/knowledge/add-website` | `ai.add_knowledge_website` | tenant | login_required |
| `/ai/knowledge/search` | `ai.search_knowledge` | tenant | login_required |
| `/ai/knowledge/summary` | `ai.get_knowledge_summary` | tenant | login_required |
| `/ai/learning/evolve` | `ai.evolve_knowledge` | tenant | login_required |
| `/ai/learning/status` | `ai.learning_status` | tenant | permission_required, login_required |
| `/ai/neural-status` | `ai.neural_status` | tenant | login_required |
| `/ai/optimize-inventory` | `ai.optimize_inventory` | tenant | permission_required, login_required |
| `/ai/performance/analysis` | `ai.performance_analysis` | tenant | permission_required, login_required |
| `/ai/predict-sales` | `ai.predict_sales` | tenant | login_required |
| `/ai/quick-calc` | `ai.quick_calc` | tenant | login_required |
| `/ai/recommend-price` | `ai.recommend_price` | tenant | login_required |
| `/ai/search-market-price/<int:product_id>` | `ai.search_market_price` | tenant | get_owned_or_404, login_required |
| `/ai/smart-price` | `ai.smart_price` | tenant | login_required |
| `/ai/system/add-customer` | `ai.add_customer` | tenant | permission_required, login_required |
| `/ai/system/customer-balance/<customer_name>` | `ai.get_customer_balance` | tenant | permission_required, login_required |
| `/ai/system/customer-debt/<int:customer_id>` | `ai.analyze_customer_debt` | tenant | permission_required, login_required |
| `/ai/system/product-stock/<product_name>` | `ai.get_product_stock` | tenant | permission_required, login_required |
| `/ai/system/search/<search_term>` | `ai.search_system_data` | tenant | login_required |
| `/ai/system/summary` | `ai.get_system_summary` | tenant | login_required |
| `/ai/transformers-understand` | `ai.transformers_understand` | tenant | login_required |
| `/ai/upload-excel` | `ai.upload_excel` | tenant | login_required |

## routes.api (tenant) — 15 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/api/barcode/validate` | `api.barcode_validate` | tenant | login_required |
| `/api/check-username` | `api.check_username` | tenant | login_required |
| `/api/client-errors` | `api.client_errors` | public | — |
| `/api/currency-rate/<from_currency>/<to_currency>` | `api.currency_rate` | tenant | login_required |
| `/api/echo` | `api.echo` | tenant | login_required |
| `/api/health` | `api.health` | system | — |
| `/api/healthz` | `api.healthz` | system | — |
| `/api/inline-edit/<entity_type>/<int:entity_id>` | `api.api_inline_edit` | tenant | login_required |
| `/api/payment-fields/<payment_method>` | `api.payment_fields` | tenant | login_required |
| `/api/products/<int:product_id>/info` | `api.api_product_info` | tenant | get_owned_or_404, login_required |
| `/api/products/barcode/<barcode>` | `api.product_by_barcode` | tenant | login_required |
| `/api/products/low-stock` | `api.products_low_stock` | tenant | login_required |
| `/api/search` | `api.api_search` | tenant | login_required |
| `/api/search/<target>` | `api.api_search_target` | tenant | login_required |
| `/api/version` | `api.version` | system | — |

## routes.api_analytics (tenant) — 5 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/api/analytics/daily-stats` | `api_analytics.daily_stats` | tenant | permission_required, login_required |
| `/api/analytics/low-stock-products` | `api_analytics.low_stock_products` | tenant | permission_required, login_required |
| `/api/analytics/overdue-payments` | `api_analytics.overdue_payments` | tenant | permission_required, login_required |
| `/api/analytics/revenue-trend` | `api_analytics.revenue_trend` | tenant | permission_required, login_required |
| `/api/analytics/top-customers` | `api_analytics.top_customers` | tenant | permission_required, login_required |

## routes.api_docs (public) — 3 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/api-docs/` | `api_docs.swagger_ui` | public | — |
| `/api-docs/openapi.json` | `api_docs.openapi_spec` | public | — |
| `/api-docs/redoc` | `api_docs.redoc` | public | — |

## routes.api_enhanced (tenant) — 8 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/api/v2/analytics/profit-margins` | `api_enhanced.profit_margins` | tenant | permission_required, login_required |
| `/api/v2/analytics/sales-forecast` | `api_enhanced.sales_forecast` | tenant | permission_required, login_required |
| `/api/v2/customers` | `api_enhanced.get_customers` | tenant | permission_required, login_required |
| `/api/v2/customers/<int:customer_id>` | `api_enhanced.get_customer` | tenant | get_owned_or_404, permission_required, login_required |
| `/api/v2/products/<int:product_id>` | `api_enhanced.get_product` | tenant | get_owned_or_404, permission_required, login_required |
| `/api/v2/products/search` | `api_enhanced.search_products` | tenant | permission_required, login_required |
| `/api/v2/sales` | `api_enhanced.get_sales` | tenant | permission_required, login_required |
| `/api/v2/sales/<int:sale_id>` | `api_enhanced.get_sale` | tenant | get_owned_or_404, permission_required, login_required |

## routes.approvals (tenant) — 8 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/approvals/` | `approvals.index` | tenant | permission_required, login_required |
| `/approvals/<int:request_id>` | `approvals.view` | tenant | get_owned_or_404, permission_required, login_required |
| `/approvals/<int:request_id>/approve` | `approvals.approve` | tenant | get_owned_or_404, permission_required, login_required |
| `/approvals/<int:request_id>/cancel` | `approvals.cancel` | tenant | get_owned_or_404, permission_required, login_required |
| `/approvals/<int:request_id>/reject` | `approvals.reject` | tenant | get_owned_or_404, permission_required, login_required |
| `/approvals/workflows` | `approvals.manage_workflows` | tenant | permission_required, login_required |
| `/approvals/workflows/<int:wf_id>/edit` | `approvals.edit_workflow` | tenant | permission_required, login_required |
| `/approvals/workflows/new` | `approvals.new_workflow` | tenant | permission_required, login_required |

## routes.auth (public) — 9 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/auth/login` | `auth.login` | public | — |
| `/auth/logout` | `auth.logout` | public | — |
| `/auth/payment/callback` | `auth.payment_callback` | public | — |
| `/auth/payment/create` | `auth.create_payment` | public | — |
| `/auth/payment/currencies` | `auth.available_currencies` | public | — |
| `/auth/payment/estimate` | `auth.estimate_amount` | public | — |
| `/auth/payment/status/<payment_id>` | `auth.payment_status` | public | — |
| `/auth/support` | `auth.support` | public | — |
| `/auth/thank-you` | `auth.thank_you` | public | — |

## routes.cheques (tenant) — 16 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/cheques/` | `cheques.index` | tenant | permission_required, login_required |
| `/cheques/<int:id>` | `cheques.view` | tenant | get_owned_or_404, permission_required, login_required |
| `/cheques/<int:id>/bounce` | `cheques.bounce_cheque` | tenant | get_owned_or_404, permission_required, login_required |
| `/cheques/<int:id>/cancel` | `cheques.cancel` | tenant | get_owned_or_404, login_required |
| `/cheques/<int:id>/clear` | `cheques.clear_cheque` | tenant | get_owned_or_404, permission_required, login_required |
| `/cheques/<int:id>/delete` | `cheques.delete` | tenant | get_owned_or_404, login_required |
| `/cheques/<int:id>/deposit` | `cheques.deposit_cheque` | tenant | get_owned_or_404, permission_required, login_required |
| `/cheques/<int:id>/edit` | `cheques.edit` | tenant | get_owned_or_404, permission_required, login_required |
| `/cheques/<int:id>/restore` | `cheques.restore` | tenant | get_owned_or_404, login_required |
| `/cheques/alerts` | `cheques.alerts` | tenant | permission_required, login_required |
| `/cheques/api/alerts` | `cheques.api_alerts` | tenant | login_required |
| `/cheques/api/stats` | `cheques.api_stats` | tenant | login_required |
| `/cheques/archived` | `cheques.archived` | tenant | login_required |
| `/cheques/create` | `cheques.create` | tenant | permission_required, login_required |
| `/cheques/incoming` | `cheques.incoming` | tenant | permission_required, login_required |
| `/cheques/outgoing` | `cheques.outgoing` | tenant | permission_required, login_required |

## routes.customers (tenant) — 9 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/customers/` | `customers.index` | tenant | permission_required, login_required |
| `/customers/<int:id>` | `customers.view` | tenant | get_owned_or_404, permission_required, login_required |
| `/customers/<int:id>/balance` | `customers.customer_balance` | tenant | get_owned_or_404, login_required |
| `/customers/<int:id>/delete` | `customers.delete` | tenant | get_owned_or_404, permission_required, login_required |
| `/customers/<int:id>/edit` | `customers.edit` | tenant | get_owned_or_404, current_tenant, permission_required, login_required |
| `/customers/<int:id>/sales` | `customers.customer_sales` | tenant | get_owned_or_404, permission_required, login_required |
| `/customers/<int:id>/statement` | `customers.statement` | tenant | get_owned_or_404, permission_required, login_required |
| `/customers/api/search` | `customers.api_search` | tenant | login_required |
| `/customers/create` | `customers.create` | tenant | current_tenant, permission_required, login_required |

## routes.erp_modules (tenant) — 40 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/erp/bins` | `erp_modules.bins` | tenant | permission_required, login_required |
| `/erp/bins/create` | `erp_modules.create_bin` | tenant | permission_required, login_required |
| `/erp/dunning` | `erp_modules.dunning` | tenant | permission_required, login_required |
| `/erp/dunning/<int:id>/send` | `erp_modules.send_dunning` | tenant | permission_required, login_required |
| `/erp/dunning/generate` | `erp_modules.generate_dunning` | tenant | permission_required, login_required |
| `/erp/e-invoices` | `erp_modules.e_invoices` | tenant | permission_required, login_required |
| `/erp/e-invoices/<int:id>` | `erp_modules.view_einvoice` | tenant | permission_required, login_required |
| `/erp/e-invoices/generate/<int:sale_id>` | `erp_modules.generate_einvoice` | tenant | permission_required, login_required |
| `/erp/fiscal-periods` | `erp_modules.fiscal_periods` | tenant | tenant_id, permission_required, login_required |
| `/erp/fiscal-periods/<int:id>/close` | `erp_modules.close_fiscal_period` | tenant | login_required |
| `/erp/fiscal-periods/<int:id>/reopen` | `erp_modules.reopen_fiscal_period` | tenant | login_required |
| `/erp/fiscal-periods/create` | `erp_modules.create_fiscal_period` | tenant | permission_required, login_required |
| `/erp/lots` | `erp_modules.lots` | tenant | permission_required, login_required |
| `/erp/lots/create` | `erp_modules.create_lot` | tenant | permission_required, login_required |
| `/erp/purchase-orders` | `erp_modules.purchase_orders` | tenant | permission_required, login_required |
| `/erp/purchase-orders/<int:id>` | `erp_modules.view_purchase_order` | tenant | permission_required, login_required |
| `/erp/purchase-orders/<int:id>/approve` | `erp_modules.approve_purchase_order` | tenant | permission_required, login_required |
| `/erp/purchase-orders/<int:id>/receive` | `erp_modules.receive_purchase_order` | tenant | permission_required, login_required |
| `/erp/purchase-orders/<int:id>/submit` | `erp_modules.submit_purchase_order` | tenant | permission_required, login_required |
| `/erp/purchase-orders/create` | `erp_modules.create_purchase_order` | tenant | permission_required, login_required |
| `/erp/quotations` | `erp_modules.quotations` | tenant | permission_required, login_required |
| `/erp/quotations/<int:id>` | `erp_modules.view_quotation` | tenant | permission_required, login_required |
| `/erp/quotations/<int:id>/convert` | `erp_modules.convert_quotation` | tenant | permission_required, login_required |
| `/erp/quotations/<int:id>/delete` | `erp_modules.delete_quotation` | tenant | permission_required, login_required |
| `/erp/quotations/<int:id>/duplicate` | `erp_modules.duplicate_quotation` | tenant | permission_required, login_required |
| `/erp/quotations/<int:id>/print` | `erp_modules.print_quotation` | tenant | permission_required, login_required |
| `/erp/quotations/<int:id>/status` | `erp_modules.update_quotation_status` | tenant | permission_required, login_required |
| `/erp/quotations/create` | `erp_modules.create_quotation` | tenant | permission_required, login_required |
| `/erp/recurring-expenses` | `erp_modules.recurring_expenses` | tenant | permission_required, login_required |
| `/erp/recurring-expenses/<int:id>/toggle` | `erp_modules.toggle_recurring_expense` | tenant | permission_required, login_required |
| `/erp/recurring-expenses/create` | `erp_modules.create_recurring_expense` | tenant | permission_required, login_required |
| `/erp/stock-takes` | `erp_modules.stock_takes` | tenant | permission_required, login_required |
| `/erp/stock-takes/<int:id>` | `erp_modules.view_stocktake` | tenant | permission_required, login_required |
| `/erp/stock-takes/<int:id>/approve` | `erp_modules.approve_stocktake` | tenant | login_required |
| `/erp/stock-takes/<int:id>/count` | `erp_modules.update_stocktake_count` | tenant | permission_required, login_required |
| `/erp/stock-takes/create` | `erp_modules.create_stocktake` | tenant | permission_required, login_required |
| `/erp/stock-transfers` | `erp_modules.stock_transfers` | tenant | permission_required, login_required |
| `/erp/stock-transfers/<int:id>/receive` | `erp_modules.receive_stock_transfer` | tenant | permission_required, login_required |
| `/erp/stock-transfers/<int:id>/send` | `erp_modules.send_stock_transfer` | tenant | permission_required, login_required |
| `/erp/stock-transfers/create` | `erp_modules.create_stock_transfer` | tenant | permission_required, login_required |

## routes.expenses (tenant) — 11 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/expenses/` | `expenses.index` | tenant | permission_required, login_required |
| `/expenses/<int:id>` | `expenses.view` | tenant | get_owned_or_404, permission_required, login_required |
| `/expenses/<int:id>/archive` | `expenses.archive` | tenant | permission_required, login_required |
| `/expenses/<int:id>/delete` | `expenses.delete` | tenant | permission_required, login_required |
| `/expenses/<int:id>/edit` | `expenses.edit` | tenant | permission_required, login_required |
| `/expenses/<int:id>/print` | `expenses.print_expense` | tenant | get_owned_or_404, permission_required, login_required |
| `/expenses/<int:id>/restore` | `expenses.restore` | tenant | permission_required, login_required |
| `/expenses/archived` | `expenses.archived` | tenant | permission_required, login_required |
| `/expenses/categories` | `expenses.categories` | tenant | permission_required, login_required |
| `/expenses/categories/create` | `expenses.create_category` | tenant | permission_required, login_required |
| `/expenses/create` | `expenses.create` | tenant | permission_required, login_required |

## routes.gamification (tenant) — 3 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/gamification/award/<action>` | `gamification.award_points` | tenant | login_required |
| `/gamification/leaderboard` | `gamification.leaderboard` | tenant | login_required |
| `/gamification/my-stats` | `gamification.my_stats` | tenant | login_required |

## routes.graphql (tenant) — 2 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/graphql` | `graphql.graphql_query` | tenant | permission_required, login_required |
| `/graphql/playground` | `graphql.graphql_playground` | tenant | permission_required, login_required |

## routes.hr (tenant) — 21 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/hr/` | `hr.dashboard` | tenant | permission_required, login_required |
| `/hr/api/employee/<int:id>/leave-balance` | `hr.api_leave_balance` | tenant | get_owned_or_404, permission_required, login_required |
| `/hr/api/employees` | `hr.api_employees` | tenant | permission_required, login_required |
| `/hr/departments` | `hr.departments` | tenant | permission_required, login_required |
| `/hr/departments/<int:id>/edit` | `hr.edit_department` | tenant | permission_required, login_required |
| `/hr/departments/create` | `hr.create_department` | tenant | permission_required, login_required |
| `/hr/employees` | `hr.employees` | tenant | permission_required, login_required |
| `/hr/employees/<int:id>` | `hr.view_employee` | tenant | get_owned_or_404, permission_required, login_required |
| `/hr/employees/<int:id>/edit` | `hr.edit_employee` | tenant | get_owned_or_404, permission_required, login_required |
| `/hr/employees/create` | `hr.create_employee` | tenant | permission_required, login_required |
| `/hr/leave` | `hr.leave_requests` | tenant | permission_required, login_required |
| `/hr/leave-types` | `hr.leave_types` | tenant | permission_required, login_required |
| `/hr/leave/<int:id>/approve` | `hr.approve_leave` | tenant | permission_required, login_required |
| `/hr/leave/<int:id>/cancel` | `hr.cancel_leave` | tenant | permission_required, login_required |
| `/hr/leave/<int:id>/reject` | `hr.reject_leave` | tenant | permission_required, login_required |
| `/hr/leave/create` | `hr.create_leave` | tenant | permission_required, login_required |
| `/hr/payroll` | `hr.payroll` | tenant | permission_required, login_required |
| `/hr/payroll/<int:id>` | `hr.view_payslip` | tenant | get_owned_or_404, permission_required, login_required |
| `/hr/payroll/<int:id>/approve` | `hr.approve_payslip` | tenant | get_owned_or_404, permission_required, login_required |
| `/hr/payroll/<int:id>/pay` | `hr.mark_payslip_paid` | tenant | get_owned_or_404, permission_required, login_required |
| `/hr/payroll/generate` | `hr.generate_payroll` | tenant | permission_required, login_required |

## routes.inbound_shipments (tenant) — 8 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/inbound-shipments` | `inbound_shipments.list_inbound` | tenant | permission_required, login_required |
| `/inbound-shipments/<int:id>` | `inbound_shipments.view_inbound` | tenant | permission_required, login_required |
| `/inbound-shipments/<int:id>/arrive` | `inbound_shipments.arrive_inbound` | tenant | permission_required, login_required |
| `/inbound-shipments/<int:id>/cancel` | `inbound_shipments.cancel_inbound` | tenant | permission_required, login_required |
| `/inbound-shipments/<int:id>/close` | `inbound_shipments.close_inbound` | tenant | permission_required, login_required |
| `/inbound-shipments/<int:id>/inspect` | `inbound_shipments.inspect_inbound` | tenant | permission_required, login_required |
| `/inbound-shipments/<int:id>/put-away` | `inbound_shipments.put_away_inbound` | tenant | permission_required, login_required |
| `/inbound-shipments/create` | `inbound_shipments.create_inbound` | tenant | tenant_id, permission_required, login_required |

## routes.language (public) — 1 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/language/set/<lang>` | `language.set_language` | public | — |

## routes.ledger (tenant) — 28 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/ledger/` | `ledger.index` | tenant | permission_required, login_required |
| `/ledger/account/<int:id>` | `ledger.account_ledger` | tenant | permission_required, login_required |
| `/ledger/account/<int:id>/statement` | `ledger.account_statement` | tenant | permission_required, login_required |
| `/ledger/accounts` | `ledger.accounts` | tenant | login_required |
| `/ledger/accounts-tree` | `ledger.accounts_tree` | tenant | permission_required, login_required |
| `/ledger/accounts/<int:id>/delete` | `ledger.delete_account` | tenant | login_required |
| `/ledger/accounts/<int:id>/edit` | `ledger.edit_account` | tenant | login_required |
| `/ledger/accounts/add` | `ledger.add_account` | tenant | login_required |
| `/ledger/aging-analysis` | `ledger.aging_analysis` | tenant | permission_required, login_required |
| `/ledger/api/account-balance/<int:account_id>` | `ledger.api_account_balance` | tenant | login_required |
| `/ledger/api/account-statement/<int:account_id>` | `ledger.api_account_statement` | tenant | login_required |
| `/ledger/api/accounts/search` | `ledger.api_search_accounts` | tenant | permission_required, login_required |
| `/ledger/api/calculate-journal-balance` | `ledger.api_calculate_journal_balance` | tenant | permission_required, login_required |
| `/ledger/balance-sheet` | `ledger.balance_sheet` | tenant | permission_required, login_required |
| `/ledger/cash-flow` | `ledger.cash_flow` | tenant | permission_required, login_required |
| `/ledger/corporate-tax` | `ledger.corporate_tax` | tenant | tenant_id, get_current_tenant_id, current_tenant, scope, permission_required, login_required |
| `/ledger/corporate-tax/post` | `ledger.corporate_tax_post` | tenant | tenant_id, get_current_tenant_id, current_tenant, scope, permission_required, login_required |
| `/ledger/entry/<int:id>` | `ledger.view_entry` | tenant | get_owned_or_404, permission_required, login_required |
| `/ledger/entry/<int:id>/approve` | `ledger.approve_entry` | tenant | login_required |
| `/ledger/entry/<int:id>/delete` | `ledger.delete_entry` | tenant | login_required |
| `/ledger/entry/<int:id>/reverse` | `ledger.reverse_entry` | tenant | get_owned_or_404, permission_required, login_required |
| `/ledger/income-statement` | `ledger.income_statement` | tenant | permission_required, login_required |
| `/ledger/journal-entries` | `ledger.journal_entries` | tenant | permission_required, login_required |
| `/ledger/manual-entry` | `ledger.manual_entry` | tenant | permission_required, login_required |
| `/ledger/reports` | `ledger.reports` | tenant | permission_required, login_required |
| `/ledger/settings` | `ledger.settings` | tenant | login_required |
| `/ledger/trial-balance` | `ledger.trial_balance` | tenant | permission_required, login_required |
| `/ledger/vaults` | `ledger.vaults` | tenant | login_required |

## routes.main (public) — 2 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/` | `main.index` | public | — |
| `/dashboard` | `main.dashboard` | tenant | tenant_id, get_current_tenant_id, current_tenant, login_required |

## routes.monitoring (platform) — 3 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/monitoring/dashboard` | `monitoring.dashboard` | platform | login_required |
| `/monitoring/health` | `monitoring.health` | system | — |
| `/monitoring/metrics` | `monitoring.metrics` | platform | login_required |

## routes.owner (platform) — 86 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/owner/activity-monitor` | `owner.activity_monitor` | platform | owner_required, login_required |
| `/owner/api-keys` | `owner.api_keys` | platform | owner_required, login_required |
| `/owner/api-keys/<int:id>/toggle` | `owner.toggle_api_key` | platform | get_owned_or_404, owner_required, login_required |
| `/owner/archived` | `owner.archived` | platform | owner_required, login_required |
| `/owner/audit-logs` | `owner.audit_logs` | platform | owner_required, login_required |
| `/owner/backup-now` | `owner.backup_now` | platform | permission_required, login_required |
| `/owner/backups/custom-restore/<filename>` | `owner.custom_restore_backup` | platform | owner_required, login_required |
| `/owner/backups/delete` | `owner.delete_backup` | platform | owner_required, login_required |
| `/owner/backups/download/<filename>` | `owner.download_backup` | platform | permission_required, login_required |
| `/owner/backups/list` | `owner.list_backups` | platform | permission_required, login_required |
| `/owner/backups/restore/<filename>` | `owner.restore_backup` | platform | owner_required, login_required |
| `/owner/backups/verify-latest` | `owner.verify_latest_backup` | platform | permission_required, login_required |
| `/owner/backups/verify/<filename>` | `owner.verify_backup` | platform | permission_required, login_required |
| `/owner/browse-table/<table_name>` | `owner.browse_table` | platform | owner_required, login_required |
| `/owner/cards-vault` | `owner.cards_vault` | platform | owner_required, login_required |
| `/owner/cards-vault/<int:id>/view` | `owner.view_card` | platform | get_owned_or_404, owner_required, login_required |
| `/owner/clear-cache` | `owner.clear_cache` | platform | owner_required, login_required |
| `/owner/company-info` | `owner.company_info` | platform | owner_required, login_required |
| `/owner/compliance-credentials` | `owner.compliance_credentials` | platform | tenant_id, owner_required, login_required |
| `/owner/config` | `owner.config` | platform | owner_required, login_required |
| `/owner/constants` | `owner.constants_index` | platform | owner_required, login_required |
| `/owner/constants/<group>` | `owner.constants_group` | platform | owner_required, login_required |
| `/owner/constants/<group>/add` | `owner.constants_add` | platform | owner_required, login_required |
| `/owner/constants/<group>/label` | `owner.constants_label` | platform | owner_required, login_required |
| `/owner/constants/<group>/visibility` | `owner.constants_visibility` | platform | owner_required, login_required |
| `/owner/convert-database` | `owner.convert_database` | platform | owner_required, login_required |
| `/owner/currency-settings` | `owner.currency_settings` | platform | owner_required, login_required |
| `/owner/customer-insights` | `owner.customer_insights` | platform | owner_required, login_required |
| `/owner/dashboard` | `owner.dashboard` | platform | owner_required, login_required |
| `/owner/data-cleanup` | `owner.data_cleanup` | platform | owner_required, login_required |
| `/owner/database-optimize` | `owner.database_optimize` | platform | owner_required, login_required |
| `/owner/database-tools` | `owner.database_tools` | platform | owner_required, login_required |
| `/owner/edit-table-data/<table_name>` | `owner.edit_table_data` | platform | owner_required, login_required |
| `/owner/email-settings` | `owner.email_settings` | platform | owner_required, login_required |
| `/owner/error-logs` | `owner.error_logs` | platform | owner_required, login_required |
| `/owner/error-logs/<int:log_id>/resolve` | `owner.error_log_resolve` | platform | owner_required, login_required |
| `/owner/export-database` | `owner.export_database` | platform | owner_required, login_required |
| `/owner/export-excel/<table_name>` | `owner.export_excel` | platform | owner_required, login_required |
| `/owner/financial-dashboard-advanced` | `owner.financial_dashboard_advanced` | platform | owner_required, login_required |
| `/owner/financial-overview` | `owner.financial_overview` | platform | owner_required, login_required |
| `/owner/forecasting` | `owner.forecasting` | platform | owner_required, login_required |
| `/owner/fx-revaluation/` | `owner.fx_revaluation` | platform | permission_required, login_required |
| `/owner/guide` | `owner.owner_guide` | platform | owner_required, login_required |
| `/owner/import-export-tools` | `owner.import_export_tools` | platform | owner_required, login_required |
| `/owner/incidents` | `owner.incidents` | platform | owner_required, login_required |
| `/owner/integrations` | `owner.integrations` | platform | owner_required, login_required |
| `/owner/integrations/update/<service>` | `owner.update_integration` | platform | owner_required, login_required |
| `/owner/invoice-settings` | `owner.invoice_settings` | platform | owner_required, login_required |
| `/owner/ip-whitelist` | `owner.ip_whitelist` | platform | owner_required, login_required |
| `/owner/ip-whitelist/<int:index>/delete` | `owner.delete_ip_whitelist` | platform | owner_required, login_required |
| `/owner/login-history` | `owner.login_history` | platform | owner_required, login_required |
| `/owner/notification-templates` | `owner.notification_templates` | platform | owner_required, login_required |
| `/owner/partners` | `owner.partners` | platform | tenant_id, scope, owner_required, login_required |
| `/owner/payment-gateways` | `owner.payment_gateways` | platform | owner_required, login_required |
| `/owner/performance-metrics` | `owner.performance_metrics` | platform | owner_required, login_required |
| `/owner/plans` | `owner.plans` | platform | owner_required, login_required |
| `/owner/plans/<int:plan_id>/toggle` | `owner.toggle_plan` | platform | owner_required, login_required |
| `/owner/preview-invoice/<template>` | `owner.preview_invoice` | platform | owner_required, login_required |
| `/owner/preview-receipt/<template>` | `owner.preview_receipt` | platform | owner_required, login_required |
| `/owner/product-performance` | `owner.product_performance` | platform | owner_required, login_required |
| `/owner/roles-permissions` | `owner.roles_permissions` | platform | owner_required, login_required |
| `/owner/roles/<int:role_id>/permissions` | `owner.update_role_permissions` | platform | owner_required, login_required |
| `/owner/sales-insights` | `owner.sales_insights` | platform | owner_required, login_required |
| `/owner/scheduled-backups` | `owner.scheduled_backups` | platform | permission_required, login_required |
| `/owner/security-alerts` | `owner.security_alerts` | platform | owner_required, login_required |
| `/owner/security-alerts/<int:id>/resolve` | `owner.resolve_alert` | platform | get_owned_or_404, owner_required, login_required |
| `/owner/sms-settings` | `owner.sms_settings` | platform | owner_required, login_required |
| `/owner/support-tickets` | `owner.support_inbox` | platform | owner_required, login_required |
| `/owner/support-tickets/<int:ticket_id>/status` | `owner.support_ticket_status` | platform | owner_required, login_required |
| `/owner/system-config` | `owner.system_config` | platform | owner_required, login_required |
| `/owner/system-health` | `owner.system_health` | platform | owner_required, login_required |
| `/owner/system-stats` | `owner.system_stats` | platform | owner_required, login_required |
| `/owner/tax-rulesets` | `owner.tax_rulesets` | platform | tenant_id, owner_required, login_required |
| `/owner/tax-settings` | `owner.tax_settings` | platform | owner_required, login_required |
| `/owner/tenants` | `owner.tenants_list` | platform | owner_required, login_required |
| `/owner/tenants/<int:id>` | `owner.tenant_detail` | platform | tenant_id, owner_required, login_required |
| `/owner/tenants/<int:id>/activate` | `owner.tenant_activate` | platform | owner_required, login_required |
| `/owner/tenants/<int:id>/edit` | `owner.tenant_edit` | platform | owner_required, login_required |
| `/owner/tenants/<int:id>/impersonate` | `owner.tenant_impersonate` | platform | tenant_id, owner_required, login_required |
| `/owner/tenants/<int:id>/suspend` | `owner.tenant_suspend` | platform | owner_required, login_required |
| `/owner/tenants/impersonate/exit` | `owner.tenant_impersonate_exit` | platform | tenant_id, owner_required, login_required |
| `/owner/tenants/new` | `owner.tenant_new` | platform | owner_required, login_required |
| `/owner/truncate-table` | `owner.truncate_table` | platform | owner_required, login_required |
| `/owner/verify-backups` | `owner.verify_backups` | platform | permission_required, login_required |
| `/owner/whatsapp-settings` | `owner.whatsapp_settings` | platform | owner_required, login_required |

## routes.payment_vault (platform) — 40 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/payment-vault/` | `payment_vault.index` | platform | login_required |
| `/payment-vault/api/donation` | `payment_vault.api_create_donation` | platform | — |
| `/payment-vault/api/live-stats` | `payment_vault.api_live_stats` | platform | login_required |
| `/payment-vault/api/notifications` | `payment_vault.api_notifications` | platform | login_required |
| `/payment-vault/api/package-stats/<int:package_id>` | `payment_vault.api_package_stats` | platform | login_required |
| `/payment-vault/api/purchase` | `payment_vault.api_create_purchase` | platform | — |
| `/payment-vault/api/v2/donations` | `payment_vault.api_v2_donations` | platform | login_required |
| `/payment-vault/api/v2/purchases` | `payment_vault.api_v2_purchases` | platform | login_required |
| `/payment-vault/api/v2/stats` | `payment_vault.api_v2_stats` | platform | login_required |
| `/payment-vault/auto-approve` | `payment_vault.trigger_auto_approve` | platform | login_required |
| `/payment-vault/card/<int:card_id>/decrypt` | `payment_vault.decrypt_card` | platform | login_required |
| `/payment-vault/cards` | `payment_vault.cards` | platform | login_required |
| `/payment-vault/change-password` | `payment_vault.change_password` | platform | login_required |
| `/payment-vault/dashboard` | `payment_vault.dashboard` | platform | login_required |
| `/payment-vault/donation/<int:donation_id>` | `payment_vault.donation_detail` | platform | login_required |
| `/payment-vault/donation/<int:donation_id>/approve` | `payment_vault.approve_donation` | platform | login_required |
| `/payment-vault/donation/<int:donation_id>/reject` | `payment_vault.reject_donation` | platform | login_required |
| `/payment-vault/donations` | `payment_vault.donations` | platform | login_required |
| `/payment-vault/export/cards` | `payment_vault.export_cards` | platform | login_required |
| `/payment-vault/export/donations` | `payment_vault.export_donations` | platform | login_required |
| `/payment-vault/export/purchases` | `payment_vault.export_purchases` | platform | login_required |
| `/payment-vault/export/report-pdf` | `payment_vault.export_report_pdf` | platform | login_required |
| `/payment-vault/health` | `payment_vault.health_check` | platform | — |
| `/payment-vault/lock` | `payment_vault.lock_vault` | platform | login_required |
| `/payment-vault/lock/<int:vault_id>` | `payment_vault.lock_vault_json` | platform | login_required |
| `/payment-vault/metrics` | `payment_vault.system_metrics` | platform | login_required |
| `/payment-vault/package/<int:package_id>/delete` | `payment_vault.delete_package` | platform | login_required |
| `/payment-vault/package/<int:package_id>/edit` | `payment_vault.edit_package` | platform | login_required |
| `/payment-vault/package/<int:package_id>/toggle` | `payment_vault.toggle_package_status` | platform | login_required |
| `/payment-vault/packages-management` | `payment_vault.packages_management` | platform | login_required |
| `/payment-vault/process-payment` | `payment_vault.process_payment` | platform | — |
| `/payment-vault/purchase/<int:id>` | `payment_vault.purchase_detail` | platform | login_required |
| `/payment-vault/purchase/<int:id>/activate` | `payment_vault.activate_purchase` | platform | login_required |
| `/payment-vault/purchases` | `payment_vault.view_purchases` | platform | login_required |
| `/payment-vault/reports` | `payment_vault.reports` | platform | login_required |
| `/payment-vault/settings` | `payment_vault.settings` | platform | login_required |
| `/payment-vault/unlock` | `payment_vault.unlock_vault` | platform | login_required |
| `/payment-vault/unlock/<int:vault_id>` | `payment_vault.unlock_vault_json` | platform | login_required |
| `/payment-vault/webhook/nowpayments` | `payment_vault.nowpayments_webhook` | platform | — |
| `/payment-vault/webhook/stripe` | `payment_vault.stripe_webhook` | platform | — |

## routes.payments (tenant) — 20 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/payments/api/customer-balance/<int:customer_id>` | `payments.api_customer_balance` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/archive/<int:id>` | `payments.archive_payment_json` | tenant | permission_required, login_required |
| `/payments/archived` | `payments.archived_receipts` | tenant | permission_required, login_required |
| `/payments/create_from_sale/<int:sale_id>` | `payments.create_from_sale` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/create_payment/<int:purchase_id>` | `payments.create_payment` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/payments/<int:id>` | `payments.view_payment` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/payments/<int:id>/archive` | `payments.archive_payment` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/payments/<int:id>/delete` | `payments.delete_payment` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/payments/<int:id>/print` | `payments.print_payment` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/payments/<int:id>/restore` | `payments.restore_payment` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/receipts` | `payments.receipts` | tenant | permission_required, login_required |
| `/payments/receipts/<int:id>` | `payments.view_receipt` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/receipts/<int:id>/archive` | `payments.archive_receipt` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/receipts/<int:id>/delete` | `payments.delete_receipt` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/receipts/<int:id>/print` | `payments.print_receipt` | tenant | get_owned_or_404, permission_required, login_required |
| `/payments/receipts/<int:id>/restore` | `payments.restore_receipt` | tenant | permission_required, login_required |
| `/payments/receipts/create` | `payments.create_receipt` | tenant | permission_required, login_required |
| `/payments/search-entities` | `payments.search_entities` | tenant | permission_required, login_required |
| `/payments/voucher/create` | `payments.create_voucher` | tenant | permission_required, login_required |
| `/payments/voucher/submit` | `payments.create_voucher_submit` | tenant | get_owned_or_404, permission_required, login_required |

## routes.products (tenant) — 9 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/products/` | `products.index` | tenant | permission_required, login_required |
| `/products/<int:id>` | `products.view` | tenant | get_owned_or_404, permission_required, login_required |
| `/products/<int:id>/adjust-stock` | `products.adjust_stock` | tenant | get_owned_or_404, permission_required, login_required |
| `/products/<int:id>/delete` | `products.delete` | tenant | get_owned_or_404, permission_required, login_required |
| `/products/<int:id>/edit` | `products.edit` | tenant | get_owned_or_404, permission_required, login_required |
| `/products/api/search` | `products.api_search` | tenant | permission_required, login_required |
| `/products/categories` | `products.categories` | tenant | permission_required, login_required |
| `/products/categories/create` | `products.create_category` | tenant | permission_required, login_required |
| `/products/create` | `products.create` | tenant | get_owned_or_404, permission_required, login_required |

## routes.public (public) — 12 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/contact` | `public.contact` | public | — |
| `/contract` | `public.contract` | public | — |
| `/demo` | `public.demo` | public | — |
| `/features` | `public.features` | public | — |
| `/pricing` | `public.pricing` | public | — |
| `/privacy` | `public.privacy` | public | — |
| `/robots.txt` | `public.robots` | public | — |
| `/sitemap.xml` | `public.sitemap` | public | — |
| `/sla` | `public.sla` | public | — |
| `/terms` | `public.terms` | public | — |
| `/user-guide` | `public.user_guide` | public | — |
| `/welcome` | `public.landing` | public | — |

## routes.purchases (tenant) — 7 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/purchases/` | `purchases.index` | tenant | permission_required, login_required |
| `/purchases/<int:id>` | `purchases.view` | tenant | get_owned_or_404, permission_required, login_required |
| `/purchases/<int:id>/delete` | `purchases.delete` | tenant | get_owned_or_404, permission_required, login_required |
| `/purchases/<int:id>/edit` | `purchases.edit` | tenant | get_owned_or_404, permission_required, login_required |
| `/purchases/<int:id>/print` | `purchases.print_purchase` | tenant | get_owned_or_404, permission_required, login_required |
| `/purchases/api/calculate-totals` | `purchases.api_calculate_purchase_totals` | tenant | tenant_id, get_current_tenant_id, current_tenant, scope, permission_required, login_required |
| `/purchases/create` | `purchases.create` | tenant | get_owned_or_404, tenant_id, get_current_tenant_id, current_tenant, scope, permission_required, login_required |

## routes.reports (tenant) — 19 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/reports/` | `reports.index` | tenant | permission_required, login_required |
| `/reports/ap-aging` | `reports.ap_aging` | tenant | permission_required, login_required |
| `/reports/ap-aging/export` | `reports.export_ap_aging` | tenant | current_tenant, scope, permission_required, login_required |
| `/reports/api/entity-search` | `reports.api_entity_search` | tenant | permission_required, login_required |
| `/reports/api/model_fields` | `reports.api_model_fields` | tenant | permission_required, login_required |
| `/reports/cash-flow` | `reports.cash_flow` | tenant | permission_required, login_required |
| `/reports/cash-flow/export` | `reports.export_cash_flow` | tenant | current_tenant, permission_required, login_required |
| `/reports/entity_report_fragment/<type>/<id>` | `reports.entity_report_fragment` | tenant | get_owned_or_404, permission_required, login_required |
| `/reports/inventory` | `reports.inventory` | tenant | permission_required, login_required |
| `/reports/inventory-valuation` | `reports.inventory_valuation` | tenant | permission_required, login_required |
| `/reports/inventory-valuation/export` | `reports.export_inventory_valuation` | tenant | current_tenant, scope, permission_required, login_required |
| `/reports/inventory-valuation/reconciliation` | `reports.inventory_valuation_reconciliation` | tenant | permission_required, login_required |
| `/reports/partners` | `reports.partners` | tenant | permission_required, login_required |
| `/reports/purchases` | `reports.purchases` | tenant | permission_required, login_required |
| `/reports/receivables` | `reports.receivables` | tenant | permission_required, login_required |
| `/reports/sales` | `reports.sales` | tenant | permission_required, login_required |
| `/reports/top-selling` | `reports.top_selling` | tenant | permission_required, login_required |
| `/reports/vat-report` | `reports.vat_report` | tenant | permission_required, login_required |
| `/reports/vat-report/export` | `reports.export_vat_report` | tenant | current_tenant, permission_required, login_required |

## routes.returns (tenant) — 2 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/returns/api/create` | `returns.api_create_return` | tenant | permission_required, login_required |
| `/returns/view/<int:id>` | `returns.view` | tenant | get_owned_or_404, tenant_id, permission_required, login_required |

## routes.sales (tenant) — 12 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/sales/` | `sales.index` | tenant | permission_required, login_required |
| `/sales/<int:id>` | `sales.view` | tenant | get_owned_or_404, permission_required, login_required |
| `/sales/<int:id>/archive` | `sales.archive` | tenant | get_owned_or_404, permission_required, login_required |
| `/sales/<int:id>/cancel` | `sales.cancel` | tenant | get_owned_or_404, permission_required, login_required |
| `/sales/<int:id>/delete` | `sales.delete` | tenant | get_owned_or_404, permission_required, login_required |
| `/sales/<int:id>/edit` | `sales.edit` | tenant | get_owned_or_404, permission_required, login_required |
| `/sales/<int:id>/print` | `sales.print_invoice` | tenant | get_owned_or_404, permission_required, login_required |
| `/sales/<int:id>/restore` | `sales.restore` | tenant | get_owned_or_404, permission_required, login_required |
| `/sales/api/calculate-totals` | `sales.api_calculate_sale_totals` | tenant | permission_required, login_required |
| `/sales/api/get-price` | `sales.api_get_price` | tenant | get_owned_or_404, permission_required, login_required |
| `/sales/archived` | `sales.archived` | tenant | tenant_id, permission_required, login_required |
| `/sales/create` | `sales.create` | tenant | get_owned_or_404, permission_required, login_required |

## routes.shipments (tenant) — 10 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/shipments` | `shipments.list_shipments` | tenant | permission_required, login_required |
| `/shipments/<int:id>` | `shipments.view_shipment` | tenant | permission_required, login_required |
| `/shipments/<int:id>/arrive` | `shipments.arrive_shipment` | tenant | permission_required, login_required |
| `/shipments/<int:id>/cancel` | `shipments.cancel_shipment` | tenant | permission_required, login_required |
| `/shipments/<int:id>/close` | `shipments.close_shipment` | tenant | permission_required, login_required |
| `/shipments/<int:id>/send` | `shipments.send_shipment` | tenant | permission_required, login_required |
| `/shipments/<int:id>/start-selling` | `shipments.start_selling` | tenant | permission_required, login_required |
| `/shipments/api/products` | `shipments.api_products` | tenant | login_required |
| `/shipments/api/warehouses` | `shipments.api_warehouses` | tenant | login_required |
| `/shipments/create` | `shipments.create_shipment` | tenant | tenant_id, permission_required, login_required |

## routes.suppliers (tenant) — 7 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/suppliers/` | `suppliers.index` | tenant | permission_required, login_required |
| `/suppliers/<int:id>` | `suppliers.view` | tenant | get_owned_or_404, permission_required, login_required |
| `/suppliers/<int:id>/delete` | `suppliers.delete` | tenant | get_owned_or_404, permission_required, login_required |
| `/suppliers/<int:id>/edit` | `suppliers.edit` | tenant | get_owned_or_404, current_tenant, permission_required, login_required |
| `/suppliers/<int:id>/statement` | `suppliers.statement` | tenant | get_owned_or_404, login_required |
| `/suppliers/api/search` | `suppliers.api_search` | tenant | permission_required, login_required |
| `/suppliers/create` | `suppliers.create` | tenant | current_tenant, permission_required, login_required |

## routes.support (tenant) — 3 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/support/tickets` | `support.tickets_list` | tenant | tenant_id, get_current_tenant_id, current_tenant, scope, login_required |
| `/support/tickets/<int:id>` | `support.ticket_view` | tenant | get_owned_or_404, login_required |
| `/support/tickets/new` | `support.ticket_new` | tenant | tenant_id, get_current_tenant_id, current_tenant, scope, login_required |

## routes.users (tenant) — 7 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/users/` | `users.index` | tenant | tenant_id, login_required |
| `/users/<int:id>` | `users.view` | tenant | get_owned_or_404, scope, login_required |
| `/users/<int:id>/delete` | `users.delete` | tenant | get_owned_or_404, login_required |
| `/users/<int:id>/edit` | `users.edit` | tenant | get_owned_or_404, login_required |
| `/users/<int:id>/toggle-active` | `users.toggle_active` | tenant | get_owned_or_404, login_required |
| `/users/change-password` | `users.change_password` | tenant | login_required |
| `/users/create` | `users.create` | tenant | tenant_id, scope, login_required |

## routes.warehouse (tenant) — 11 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/warehouse/` | `warehouse.index` | tenant | permission_required, login_required |
| `/warehouse/<int:id>` | `warehouse.view_warehouse` | tenant | get_owned_or_404, permission_required, login_required |
| `/warehouse/<int:id>/delete` | `warehouse.delete_warehouse` | tenant | get_owned_or_404, login_required |
| `/warehouse/add-stock/<int:product_id>` | `warehouse.add_stock` | tenant | get_owned_or_404, permission_required, login_required |
| `/warehouse/api/upload_product_image` | `warehouse.upload_product_image` | tenant | permission_required, login_required |
| `/warehouse/create` | `warehouse.create_warehouse` | tenant | get_owned_or_404, login_required |
| `/warehouse/create-warehouse` | `warehouse.create_warehouse` | tenant | get_owned_or_404, login_required |
| `/warehouse/list` | `warehouse.list_warehouses` | tenant | permission_required, login_required |
| `/warehouse/low-stock` | `warehouse.low_stock` | tenant | permission_required, login_required |
| `/warehouse/movements` | `warehouse.movements` | tenant | get_owned_or_404, permission_required, login_required |
| `/warehouse/out-of-stock` | `warehouse.out_of_stock` | tenant | permission_required, login_required |

## routes.whatsapp (tenant) — 3 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/whatsapp/send-invoice/<int:sale_id>` | `whatsapp.send_invoice` | tenant | get_owned_or_404, permission_required, login_required |
| `/whatsapp/send-reminder/<int:customer_id>` | `whatsapp.send_reminder` | tenant | get_owned_or_404, login_required |
| `/whatsapp/test` | `whatsapp.test_connection` | tenant | login_required |

## routes.writeoffs (tenant) — 5 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/writeoffs/` | `writeoffs.index` | tenant | permission_required, login_required |
| `/writeoffs/` | `writeoffs.create` | tenant | get_owned_or_404, permission_required, login_required |
| `/writeoffs/<int:write_off_id>` | `writeoffs.detail` | tenant | permission_required, login_required |
| `/writeoffs/<int:write_off_id>/void` | `writeoffs.void` | tenant | permission_required, login_required |
| `/writeoffs/new` | `writeoffs.new` | tenant | get_owned_or_404, permission_required, login_required |

## utils.monitoring (system) — 3 مسار

| Path | Endpoint | Scope | Markers |
|---|---|---|---|
| `/ai-metrics` | `ai_metrics` | system | — |
| `/health` | `health_check` | system | — |
| `/metrics` | `metrics` | system | — |

## الملخص

* **إجمالي المسارات:** 516
* **platform:** 127
* **public:** 27
* **system:** 7
* **tenant:** 355

### أكثر علامات العزل استخدامًا
* `login_required`: 477
* `permission_required`: 263
* `get_owned_or_404`: 90
* `owner_required`: 79
* `tenant_id`: 20
* `current_tenant`: 15
* `scope`: 12
* `get_current_tenant_id`: 7

**ملاحظة قانونية:** هذه المسارد حصرًا على مستوى الكود. لا شرط فيها
يتعلق بمعايير التدقيق الخارجي أو اعتماد منصات سلطة. الامتثال القانوني
لكل دولة يتطلب عقدًا وشهادة من السلطة؛ هذا المستند يتتبع العزل التقني
بين الشركات فقط.