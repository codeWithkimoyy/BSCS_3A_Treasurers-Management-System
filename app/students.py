from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .audit import log_audit
from .db import db, format_name, next_id
from .decorators import role_required, validate_csrf

bp = Blueprint('students', __name__)
ROLES_MANAGE = ('admin', 'mayor', 'treasurer')

ACTIVE_FILTER = {'deleted': {'$ne': True}}


@bp.route('/students')
@login_required
def index():
    students = list(db.students.find(ACTIVE_FILTER).sort([('is_active', -1), ('name', 1)]))
    return render_template('students.html', students=students)


@bp.route('/students/add', methods=['POST'])
@login_required
@role_required(*ROLES_MANAGE)
def add():
    validate_csrf()
    try:
        db.students.insert_one({
            '_id': next_id('students'),
            'student_id': request.form['student_id'].strip(),
            'name': format_name(request.form['name']),
            'course': request.form.get('course', ''),
            'year': request.form.get('year', ''),
            'email': request.form.get('email', ''),
            'phone': request.form.get('phone', ''),
            'is_active': 1,
            'deleted': False,
            'created_at': datetime.now(),
        })
        log_audit('student_add', target=request.form['student_id'])
        flash('Student added', 'success')
    except Exception:
        flash('Student ID already exists', 'error')
    return redirect(url_for('students.index'))


@bp.route('/students/edit/<int:id>', methods=['POST'])
@login_required
@role_required(*ROLES_MANAGE)
def edit(id):
    validate_csrf()
    db.students.update_one({'_id': id}, {'$set': {
        'name': format_name(request.form['name']),
        'course': request.form.get('course', ''),
        'year': request.form.get('year', ''),
        'email': request.form.get('email', ''),
        'phone': request.form.get('phone', ''),
        'is_active': int(request.form.get('is_active', 0)),
    }})
    log_audit('student_edit', target=id)
    flash('Student updated', 'success')
    return redirect(url_for('students.index'))


@bp.route('/students/delete/<int:id>', methods=['POST'])
@login_required
@role_required(*ROLES_MANAGE)
def delete(id):
    validate_csrf()
    # Soft-delete: preserve payment/transaction history referencing this student.
    db.students.update_one({'_id': id}, {'$set': {'deleted': True, 'is_active': 0}})
    log_audit('student_delete', target=id)
    flash('Student removed', 'success')
    return redirect(url_for('students.index'))
