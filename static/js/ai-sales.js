// AI-Enhanced Sales Form
// Auto-pricing, stock alerts, and smart recommendations

$(document).ready(function() {
    
    // توصية السعر عند اختيار منتج وعميل
    function checkPriceRecommendation(productId, customerId, lineIndex) {
        if (!productId || !customerId) return;
        
        $.ajax({
            url: '/ai/recommend-price',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                product_id: productId,
                customer_id: customerId
            }),
            success: function(response) {
                const priceInput = $(`#unit_price_${lineIndex}`);
                const currentPrice = parseFloat(priceInput.val()) || 0;
                
                if (currentPrice === 0 || Math.abs(currentPrice - response.recommended_price) > 0.01) {
                    // إظهار توصية
                    const badge = `
                        <span class="badge badge-info ai-recommendation" style="margin-right: 5px;">
                            <i class="fas fa-robot"></i> ${t('Recommended')}: ${response.recommended_price.toFixed(2)}
                            <button type="button" class="btn btn-xs btn-light ml-1" onclick="applyRecommendedPrice(${lineIndex}, ${response.recommended_price})">
                                ${t('Apply')}
                            </button>
                        </span>
                    `;
                    
                    priceInput.parent().find('.ai-recommendation').remove();
                    priceInput.after(badge);
                }
            },
            error: function() {            }
        });
    }
    
    // فحص المخزون
    function checkStockAlert(productId, quantity, lineIndex) {
        if (!productId || !quantity) return;
        
        $.ajax({
            url: '/ai/check-stock',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                product_id: productId,
                quantity: quantity
            }),
            success: function(response) {
                const alertContainer = $(`#stock_alert_${lineIndex}`);
                alertContainer.empty();
                
                if (response.type === 'error') {
                    alertContainer.html(`
                        <div class="alert alert-danger alert-sm mt-2">
                            <i class="fas fa-exclamation-triangle"></i> ${response.message}
                        </div>
                    `);
                } else if (response.type === 'warning') {
                    alertContainer.html(`
                        <div class="alert alert-warning alert-sm mt-2">
                            <i class="fas fa-exclamation-circle"></i> ${response.message}
                        </div>
                    `);
                }
            }
        });
    }
    
    // تحليل سلوك العميل
    function analyzeCustomer(customerId) {
        if (!customerId) return;
        
        $.ajax({
            url: `/ai/analyze-customer/${customerId}`,
            method: 'GET',
            success: function(analysis) {
                let riskClass = 'info';
                if (analysis.risk_level === 'high') riskClass = 'danger';
                else if (analysis.risk_level === 'medium') riskClass = 'warning';
                
                const analysisHtml = `
                    <div class="alert alert-${riskClass} mt-3">
                        <h5><i class="fas fa-chart-line"></i> ${t('Customer Analysis')}</h5>
                        <p><strong>${t('Current balance:')}</strong> ${analysis.current_balance.toFixed(2)} ${t('AED')}</p>
                        <p><strong>${t('Average payment delay:')}</strong> ${analysis.avg_payment_delay_days} ${t('days')}</p>
                        <p><strong>${t('Recommendation:')}</strong> ${analysis.recommendation}</p>
                    </div>
                `;
                
                $('#customer_analysis').html(analysisHtml);
            },
            error: function() {            }
        });
    }
    
    // اقتراح سعر الصرف - uses window.BASE_CURRENCY for comparison
    function suggestExchangeRate(currency) {
        if (currency === (window.BASE_CURRENCY || 'AED')) {
            $('#exchange_rate').val('1.00');
            return;
        }
        
        $.ajax({
            url: `/ai/exchange-rate/${currency}`,
            method: 'GET',
            success: function(suggestion) {
                $('#exchange_rate').val(suggestion.suggested_rate.toFixed(6));
                
                const sourceInfo = `
                    <small class="text-muted d-block mt-1">
                        <i class="fas fa-info-circle"></i> ${suggestion.source}
                        ${suggestion.count > 0 ? `(${t('Based on')} ${suggestion.count} ${t('transactions')})` : ''}
                    </small>
                `;
                
                $('#exchange_rate').parent().find('small').remove();
                $('#exchange_rate').after(sourceInfo);
            }
        });
    }
    
    // البحث في الأسواق العالمية
    function searchGlobalMarket(productId, lineIndex) {
        if (!productId) return;
        
        $.ajax({
            url: `/ai/search-market-price/${productId}`,
            method: 'GET',
            success: function(result) {
                if (result.found && result.suggested_price_aed) {
                    const marketInfo = `
                        <div class="alert alert-success alert-sm mt-2">
                            <strong> ${t('Global market price:')}</strong><br>
                            <span class="badge badge-primary">${result.average_price_usd} USD</span>
                            <span class="badge badge-info">${result.suggested_price_aed.toFixed(2)} ${window.BASE_CURRENCY || 'AED'}</span><br>
                            <small>${result.notes || ''}</small>
                            ${result.markets ? '<br><small>' + t('Markets:') + ' ' + result.markets.join(', ') + '</small>' : ''}
                            <button type="button" class="btn btn-xs btn-success mt-1" onclick="applyMarketPrice(${lineIndex}, ${result.suggested_price_aed})">
                                ${t('Apply price')}
                            </button>
                        </div>
                    `;
                    $(`#market_info_${lineIndex}`).html(marketInfo);
                }
            },
            error: function() {            }
        });
    }
    
    // معرفة التوافق
    function findCompatibleVehicles(productId) {
        if (!productId) return;
        
        $.ajax({
            url: `/ai/find-compatible/${productId}`,
            method: 'GET',
            success: function(result) {
                if (result.found && result.vehicles && result.vehicles.length > 0) {
                    let vehiclesHtml = '<div class="alert alert-info mt-2"><h6><i class="fas fa-car"></i> ' + t('Compatible with:') + '</h6><ul class="mb-0">';
                    
                    result.vehicles.slice(0, 5).forEach(v => {
                        vehiclesHtml += `<li><strong>${v.brand}</strong>: ${v.models.join(', ')} (${v.years})`;
                        if (v.engine) vehiclesHtml += ` - ${v.engine}`;
                        vehiclesHtml += '</li>';
                    });
                    
                    if (result.total_count > 5) {
                        vehiclesHtml += `<li class="text-muted">...${t('and')} ${result.total_count - 5} ${t('others')}</li>`;
                    }
                    
                    vehiclesHtml += '</ul>';
                    if (result.notes) vehiclesHtml += `<small class="text-muted">${result.notes}</small>`;
                    vehiclesHtml += '</div>';
                    
                    $('#compatible_vehicles').html(vehiclesHtml);
                } else if (result.raw_response) {
                    $('#compatible_vehicles').html(`<div class="alert alert-info mt-2">${result.raw_response}</div>`);
                }
            },
            error: function() {            }
        });
    }
    
    // Events
    $(document).on('change', '#customer_id', function() {
        const customerId = $(this).val();
        analyzeCustomer(customerId);
        
        // إعادة فحص الأسعار لجميع الأسطر
        $('.product-select').each(function(index) {
            const productId = $(this).val();
            if (productId) {
                checkPriceRecommendation(productId, customerId, index);
            }
        });
    });
    
    $(document).on('change', '.product-select', function() {
        const lineIndex = $(this).data('line-index');
        const productId = $(this).val();
        const customerId = $('#customer_id').val();
        
        if (productId && customerId) {
            checkPriceRecommendation(productId, customerId, lineIndex);
        }
        
        if (productId) {
            searchGlobalMarket(productId, lineIndex);
            findCompatibleVehicles(productId);
        }
    });
    
    $(document).on('change', '.quantity-input', function() {
        const lineIndex = $(this).data('line-index');
        const productId = $(`.product-select[data-line-index="${lineIndex}"]`).val();
        const quantity = parseFloat($(this).val()) || 0;
        
        if (productId && quantity > 0) {
            checkStockAlert(productId, quantity, lineIndex);
        }
    });
    
    $(document).on('change', '#currency', function() {
        const currency = $(this).val();
        suggestExchangeRate(currency);
    });
    
    // Initialize
    if ($('#currency').length) {
        const initialCurrency = $('#currency').val();
        if (initialCurrency && initialCurrency !== (window.BASE_CURRENCY || 'AED')) {
            suggestExchangeRate(initialCurrency);
        }
    }
});

// تطبيق السعر الموصى به
function applyRecommendedPrice(lineIndex, price) {
    $(`#unit_price_${lineIndex}`).val(price.toFixed(2));
    $(`#unit_price_${lineIndex}`).trigger('change');
    $(`.ai-recommendation`).fadeOut();
}

// تطبيق سعر السوق العالمي
function applyMarketPrice(lineIndex, price) {
    $(`#unit_price_${lineIndex}`).val(price.toFixed(2));
    $(`#unit_price_${lineIndex}`).trigger('change');
    $(`#market_info_${lineIndex}`).fadeOut();
}

