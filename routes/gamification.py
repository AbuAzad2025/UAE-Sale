from flask import Blueprint, jsonify, render_template, abort
from flask_login import login_required, current_user
from services.gamification_service import GamificationService

gamification_bp = Blueprint('gamification', __name__, url_prefix='/gamification')

# Whitelist of game actions that can be self-awarded.  Anything outside
# this list 404s — the previous behaviour was to award arbitrary points
# for any URL segment, which let any authenticated user self-promote.
ALLOWED_AWARD_ACTIONS = frozenset({
    'first_sale', 'tenth_sale', 'hundredth_sale',
    'daily_login', 'week_streak', 'month_streak',
    'low_stock_report', 'customer_followup', 'task_completed',
})


@gamification_bp.route('/leaderboard')
@login_required
def leaderboard():
    board = GamificationService.get_leaderboard(limit=20)
    return render_template('gamification/leaderboard.html', leaderboard=board)


@gamification_bp.route('/my-stats')
@login_required
def my_stats():
    stats = GamificationService.get_user_stats(current_user.id)
    return jsonify(stats)


@gamification_bp.route('/award/<action>')
@login_required
def award_points(action):
    # SECURITY: only allow whitelisted actions to be self-awarded.
    if action not in ALLOWED_AWARD_ACTIONS:
        abort(404)
    result = GamificationService.award_points(current_user.id, action)
    return jsonify(result)
