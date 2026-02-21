from flask import render_template, send_from_directory
from flask_login import login_required
from redash.handlers.base import routes


@routes.route('/<org_slug>/profile')
@login_required
def profile_page(org_slug):
    """Render the standalone user profile page"""
    return render_template('profile.html', org_slug=org_slug)
