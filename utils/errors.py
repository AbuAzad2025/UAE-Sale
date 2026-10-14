"""Typed application errors.

Why this exists
---------------
Commit ``a362501`` removed every ``str(e)`` interpolation from the route
handlers. That was right for the reason it gave: ``str(e)`` on a SQLAlchemy
error carries the statement, the column names and the bound parameters, so a
user who reached an error branch could read the schema off it.

But that fix was too blunt. Most of the exceptions those handlers catch are
not library errors atall - they are ``ValueError`` instances the application
raises *on purpose* to tell the user what is wrong with the form:
``'اسم المستخدم "testseller" مستخدم بالفعل.'``, ``'لا يمكنك حذف حسابك
الخاص.'``, ``'كلمة المرور الحالية غير صحيحة.'``. Those strings are
hand-written, they carry no schema, and hiding them leaves the user staring
at a generic banner with no idea which field to fix.

``ValidationError`` draws that line explicitly. It subclasses ``ValueError``
so every existing ``except ValueError`` keeps working unchanged, but routes
can now tell the two apart and render only the safe ones::

    try:
        ...
    except ValidationError as e:
        flash(f'⚠️ {e}', 'danger')      # safe, hand-authored
    except Exception as e:
        logger.exception('handler failed')
        flash('⚠️ حدث خطأ غير متوقع', 'danger')   # generic; never leak str(e)

Rules for raising it:

* Only for validation and business-rule failures a user can act on.
* The message is rendered verbatim, so write it for a human: no exception
  reprs, no SQL, no ids that belong to another tenant.
* Never re-raise a library exception as a ``ValidationError`` to make its
  text visible. That re-opens the exact hole ``a362501`` closed.
"""


class ValidationError(ValueError):
    """A safe, user-facing business/validation message.

    Subclasses ``ValueError`` so ``except ValueError`` blocks in existing
    service code and routes continue to catch it with no change.
    """


__all__ = ['ValidationError']