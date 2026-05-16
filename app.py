import os
import re
import logging
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField, PasswordField, FloatField, TextAreaField, SelectField, DateField
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
import bleach

# ─── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32).hex())
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'instance', 'bodega.db'))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['WTF_CSRF_TIME_LIMIT'] = 3600
app.config['PERMANENT_SESSION_LIFETIME'] = 28800  # 8 h

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Debes iniciar sesión para acceder a esta página.'
login_manager.login_message_category = 'warning'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Models ───────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(20), nullable=False, default='operario')  # 'admin' | 'operario'
    active        = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Material(db.Model):
    __tablename__ = 'materiales'
    id            = db.Column(db.Integer, primary_key=True)
    nombre        = db.Column(db.String(120), unique=True, nullable=False)
    unidad        = db.Column(db.String(20), nullable=False, default='KG')
    stock_minimo  = db.Column(db.Float, nullable=False, default=0)
    activo        = db.Column(db.Boolean, default=True)

    @property
    def stock_actual(self):
        entradas  = db.session.query(func.coalesce(func.sum(Entrada.cantidad), 0)).filter_by(material_id=self.id).scalar()
        reempaque = db.session.query(func.coalesce(func.sum(Reempaque.cantidad_salida), 0)).filter_by(material_id=self.id).scalar()
        salidas   = db.session.query(func.coalesce(func.sum(Salida.cantidad), 0)).filter_by(material_id=self.id).scalar()
        return round(entradas - reempaque - salidas, 4)

    @property
    def estado(self):
        s = self.stock_actual
        if s <= 0:
            return 'agotado'
        elif s < self.stock_minimo:
            return 'bajo'
        else:
            return 'ok'


class Entrada(db.Model):
    __tablename__ = 'entradas'
    id          = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey('materiales.id'), nullable=False)
    cantidad    = db.Column(db.Float, nullable=False)
    fecha       = db.Column(db.Date, nullable=False, default=date.today)
    proveedor   = db.Column(db.String(120))
    notas       = db.Column(db.Text)
    usuario_id  = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    material    = db.relationship('Material', backref='entradas')
    usuario     = db.relationship('User')


class Reempaque(db.Model):
    __tablename__ = 'reempaques'
    id              = db.Column(db.Integer, primary_key=True)
    material_id     = db.Column(db.Integer, db.ForeignKey('materiales.id'), nullable=False)
    cantidad_entrada = db.Column(db.Float, nullable=False)
    cantidad_salida  = db.Column(db.Float, nullable=False)
    tiempo_minutos   = db.Column(db.Float, nullable=False)
    fecha           = db.Column(db.Date, nullable=False, default=date.today)
    notas           = db.Column(db.Text)
    usuario_id      = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    material        = db.relationship('Material', backref='reempaques')
    usuario         = db.relationship('User')


class Salida(db.Model):
    __tablename__ = 'salidas'
    id          = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey('materiales.id'), nullable=False)
    cantidad    = db.Column(db.Float, nullable=False)
    fecha       = db.Column(db.Date, nullable=False, default=date.today)
    destino     = db.Column(db.String(120))
    notas       = db.Column(db.Text)
    usuario_id  = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    material    = db.relationship('Material', backref='salidas')
    usuario     = db.relationship('User')


# ─── Login ────────────────────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ─── Forms ────────────────────────────────────────────────────────────────────
class LoginForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired(), Length(3, 80)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(6, 128)])


class MaterialForm(FlaskForm):
    nombre       = StringField('Nombre', validators=[DataRequired(), Length(1, 120)])
    unidad       = SelectField('Unidad', choices=[('KG','KG'),('UNIDAD','UNIDAD'),('LT','LT'),('MT','MT')])
    stock_minimo = FloatField('Stock Mínimo', validators=[DataRequired(), NumberRange(min=0)])


class EntradaForm(FlaskForm):
    material_id = SelectField('Material', coerce=int, validators=[DataRequired()])
    cantidad    = FloatField('Cantidad', validators=[DataRequired(), NumberRange(min=0.001)])
    fecha       = DateField('Fecha', validators=[DataRequired()])
    proveedor   = StringField('Proveedor', validators=[Optional(), Length(max=120)])
    notas       = TextAreaField('Notas', validators=[Optional(), Length(max=500)])


class ReempaqueForm(FlaskForm):
    material_id      = SelectField('Material', coerce=int, validators=[DataRequired()])
    cantidad_entrada = FloatField('Cantidad a Reempacar', validators=[DataRequired(), NumberRange(min=0.001)])
    cantidad_salida  = FloatField('Cantidad Resultante', validators=[DataRequired(), NumberRange(min=0.001)])
    tiempo_minutos   = FloatField('Tiempo (minutos)', validators=[DataRequired(), NumberRange(min=1)])
    fecha            = DateField('Fecha', validators=[DataRequired()])
    notas            = TextAreaField('Notas', validators=[Optional(), Length(max=500)])


class SalidaForm(FlaskForm):
    material_id = SelectField('Material', coerce=int, validators=[DataRequired()])
    cantidad    = FloatField('Cantidad', validators=[DataRequired(), NumberRange(min=0.001)])
    fecha       = DateField('Fecha', validators=[DataRequired()])
    destino     = StringField('Destino', validators=[Optional(), Length(max=120)])
    notas       = TextAreaField('Notas', validators=[Optional(), Length(max=500)])


class UserForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired(), Length(3, 80)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(8, 128)])
    role     = SelectField('Rol', choices=[('operario','Operario'),('admin','Administrador')])


# ─── Security helpers ─────────────────────────────────────────────────────────
def sanitize(text):
    if text is None:
        return None
    return bleach.clean(str(text).strip(), tags=[], strip=True)[:500]


# ─── Routes: Auth ─────────────────────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        username = sanitize(form.username.data)
        user = User.query.filter_by(username=username, active=True).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=False)
            session.permanent = True
            logger.info(f"Login exitoso: {username}")
            return redirect(url_for('dashboard'))
        flash('Usuario o contraseña incorrectos.', 'danger')
        logger.warning(f"Login fallido para: {username}")
    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logger.info(f"Logout: {current_user.username}")
    logout_user()
    session.clear()
    return redirect(url_for('login'))


# ─── Routes: Dashboard ────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    materiales = Material.query.filter_by(activo=True).order_by(Material.nombre).all()
    
    # Stats hoy
    entradas_hoy  = Entrada.query.filter_by(fecha=today).count()
    reempaques_hoy = Reempaque.query.filter_by(fecha=today).count()
    salidas_hoy   = Salida.query.filter_by(fecha=today).count()
    
    agotados = sum(1 for m in materiales if m.estado == 'agotado')
    bajo_min  = sum(1 for m in materiales if m.estado == 'bajo')

    # Últimos movimientos
    ultimas_entradas  = Entrada.query.order_by(Entrada.created_at.desc()).limit(5).all()
    ultimas_salidas   = Salida.query.order_by(Salida.created_at.desc()).limit(5).all()
    ultimos_reempaques = Reempaque.query.order_by(Reempaque.created_at.desc()).limit(5).all()

    return render_template('dashboard.html',
        materiales=materiales,
        entradas_hoy=entradas_hoy,
        reempaques_hoy=reempaques_hoy,
        salidas_hoy=salidas_hoy,
        agotados=agotados,
        bajo_min=bajo_min,
        ultimas_entradas=ultimas_entradas,
        ultimas_salidas=ultimas_salidas,
        ultimos_reempaques=ultimos_reempaques,
        today=today,
    )


# ─── Routes: Entradas ─────────────────────────────────────────────────────────
@app.route('/entradas', methods=['GET', 'POST'])
@login_required
def entradas():
    form = EntradaForm()
    form.material_id.choices = [(m.id, f"{m.nombre} ({m.unidad})")
                                for m in Material.query.filter_by(activo=True).order_by(Material.nombre)]
    if form.validate_on_submit():
        e = Entrada(
            material_id=form.material_id.data,
            cantidad=form.cantidad.data,
            fecha=form.fecha.data,
            proveedor=sanitize(form.proveedor.data),
            notas=sanitize(form.notas.data),
            usuario_id=current_user.id,
        )
        db.session.add(e)
        db.session.commit()
        flash('Entrada registrada correctamente.', 'success')
        return redirect(url_for('entradas'))
    
    registros = Entrada.query.order_by(Entrada.fecha.desc(), Entrada.created_at.desc()).limit(100).all()
    return render_template('entradas.html', form=form, registros=registros, today=date.today())


@app.route('/entradas/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_entrada(id):
    e = Entrada.query.get_or_404(id)
    db.session.delete(e)
    db.session.commit()
    flash('Entrada eliminada.', 'info')
    return redirect(url_for('entradas'))


# ─── Routes: Reempaques ───────────────────────────────────────────────────────
@app.route('/reempaques', methods=['GET', 'POST'])
@login_required
def reempaques():
    form = ReempaqueForm()
    form.material_id.choices = [(m.id, f"{m.nombre} ({m.unidad})")
                                for m in Material.query.filter_by(activo=True).order_by(Material.nombre)]
    if form.validate_on_submit():
        material = Material.query.get(form.material_id.data)
        if material.stock_actual < form.cantidad_entrada.data:
            flash(f'Stock insuficiente. Disponible: {material.stock_actual} {material.unidad}', 'danger')
        else:
            r = Reempaque(
                material_id=form.material_id.data,
                cantidad_entrada=form.cantidad_entrada.data,
                cantidad_salida=form.cantidad_salida.data,
                tiempo_minutos=form.tiempo_minutos.data,
                fecha=form.fecha.data,
                notas=sanitize(form.notas.data),
                usuario_id=current_user.id,
            )
            db.session.add(r)
            db.session.commit()
            flash('Reempaque registrado correctamente.', 'success')
            return redirect(url_for('reempaques'))

    registros = Reempaque.query.order_by(Reempaque.fecha.desc(), Reempaque.created_at.desc()).limit(100).all()
    return render_template('reempaques.html', form=form, registros=registros, today=date.today())


@app.route('/reempaques/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_reempaque(id):
    r = Reempaque.query.get_or_404(id)
    db.session.delete(r)
    db.session.commit()
    flash('Reempaque eliminado.', 'info')
    return redirect(url_for('reempaques'))


# ─── Routes: Salidas ──────────────────────────────────────────────────────────
@app.route('/salidas', methods=['GET', 'POST'])
@login_required
def salidas():
    form = SalidaForm()
    form.material_id.choices = [(m.id, f"{m.nombre} ({m.unidad})")
                                for m in Material.query.filter_by(activo=True).order_by(Material.nombre)]
    if form.validate_on_submit():
        material = Material.query.get(form.material_id.data)
        if material.stock_actual < form.cantidad.data:
            flash(f'Stock insuficiente. Disponible: {material.stock_actual} {material.unidad}', 'danger')
        else:
            s = Salida(
                material_id=form.material_id.data,
                cantidad=form.cantidad.data,
                fecha=form.fecha.data,
                destino=sanitize(form.destino.data),
                notas=sanitize(form.notas.data),
                usuario_id=current_user.id,
            )
            db.session.add(s)
            db.session.commit()
            flash('Salida registrada correctamente.', 'success')
            return redirect(url_for('salidas'))

    registros = Salida.query.order_by(Salida.fecha.desc(), Salida.created_at.desc()).limit(100).all()
    return render_template('salidas.html', form=form, registros=registros, today=date.today())


@app.route('/salidas/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_salida(id):
    s = Salida.query.get_or_404(id)
    db.session.delete(s)
    db.session.commit()
    flash('Salida eliminada.', 'info')
    return redirect(url_for('salidas'))


# ─── Routes: Inventario ───────────────────────────────────────────────────────
@app.route('/inventario')
@login_required
def inventario():
    materiales = Material.query.filter_by(activo=True).order_by(Material.nombre).all()
    return render_template('inventario.html', materiales=materiales)


# ─── Routes: Reportes ─────────────────────────────────────────────────────────
@app.route('/reportes')
@login_required
def reportes():
    fecha_desde = request.args.get('desde', date.today().replace(day=1).isoformat())
    fecha_hasta = request.args.get('hasta', date.today().isoformat())
    try:
        fd = date.fromisoformat(fecha_desde)
        fh = date.fromisoformat(fecha_hasta)
    except ValueError:
        fd = date.today().replace(day=1)
        fh = date.today()

    entradas  = Entrada.query.filter(Entrada.fecha.between(fd, fh)).order_by(Entrada.fecha).all()
    reempaques = Reempaque.query.filter(Reempaque.fecha.between(fd, fh)).order_by(Reempaque.fecha).all()
    salidas   = Salida.query.filter(Salida.fecha.between(fd, fh)).order_by(Salida.fecha).all()
    
    total_entradas  = sum(e.cantidad for e in entradas)
    total_reempaque = sum(r.cantidad_salida for r in reempaques)
    total_salidas   = sum(s.cantidad for s in salidas)
    total_tiempo    = sum(r.tiempo_minutos for r in reempaques)

    return render_template('reportes.html',
        entradas=entradas, reempaques=reempaques, salidas=salidas,
        total_entradas=total_entradas,
        total_reempaque=total_reempaque,
        total_salidas=total_salidas,
        total_tiempo=total_tiempo,
        fecha_desde=fd.isoformat(),
        fecha_hasta=fh.isoformat(),
    )


# ─── Routes: Admin ────────────────────────────────────────────────────────────
@app.route('/admin/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_usuarios():
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=sanitize(form.username.data)).first():
            flash('El nombre de usuario ya existe.', 'danger')
        else:
            u = User(username=sanitize(form.username.data), role=form.role.data)
            u.set_password(form.password.data)
            db.session.add(u)
            db.session.commit()
            flash('Usuario creado correctamente.', 'success')
            return redirect(url_for('admin_usuarios'))
    usuarios = User.query.order_by(User.username).all()
    return render_template('admin_usuarios.html', form=form, usuarios=usuarios)


@app.route('/admin/usuarios/toggle/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle_usuario(id):
    u = User.query.get_or_404(id)
    if u.id == current_user.id:
        flash('No puedes desactivarte a ti mismo.', 'danger')
    else:
        u.active = not u.active
        db.session.commit()
        flash(f'Usuario {"activado" if u.active else "desactivado"}.', 'info')
    return redirect(url_for('admin_usuarios'))


@app.route('/admin/materiales', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_materiales():
    form = MaterialForm()
    if form.validate_on_submit():
        nombre = sanitize(form.nombre.data).upper()
        if Material.query.filter_by(nombre=nombre).first():
            flash('El material ya existe.', 'danger')
        else:
            m = Material(nombre=nombre, unidad=form.unidad.data, stock_minimo=form.stock_minimo.data)
            db.session.add(m)
            db.session.commit()
            flash('Material agregado.', 'success')
            return redirect(url_for('admin_materiales'))
    materiales = Material.query.order_by(Material.nombre).all()
    return render_template('admin_materiales.html', form=form, materiales=materiales)


@app.route('/admin/materiales/toggle/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle_material(id):
    m = Material.query.get_or_404(id)
    m.activo = not m.activo
    db.session.commit()
    flash(f'Material {"activado" if m.activo else "desactivado"}.', 'info')
    return redirect(url_for('admin_materiales'))


# ─── API: stock en tiempo real ─────────────────────────────────────────────────
@app.route('/api/stock/<int:material_id>')
@login_required
def api_stock(material_id):
    m = Material.query.get_or_404(material_id)
    return jsonify({'stock': m.stock_actual, 'unidad': m.unidad, 'estado': m.estado})


# ─── Error handlers ───────────────────────────────────────────────────────────
@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, msg='Acceso denegado'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, msg='Página no encontrada'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, msg='Error interno del servidor'), 500


# ─── Init DB ──────────────────────────────────────────────────────────────────
def init_db():
    db.create_all()
    
    # Crear admin por defecto si no existe
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', role='admin')
        admin.set_password('Admin@2025!')
        db.session.add(admin)

    if not User.query.filter_by(username='operario').first():
        op = User(username='operario', role='operario')
        op.set_password('Operario@2025!')
        db.session.add(op)

    # Cargar materiales del catálogo
    materiales_iniciales = [
        ('Y3', 'KG', 300), ('X3', 'KG', 800), ('Y1', 'KG', 400), ('Y2', 'KG', 300),
        ('X24', 'KG', 200), ('X1', 'KG', 200), ('AMARILLO TRANSPATENTE', 'KG', 500),
        ('ROJO TRANSPARENTE', 'KG', 1000), ('NEGRO TRANSPARENTE', 'KG', 500),
        ('VERDE TRANSPARENTE', 'KG', 200), ('AZUL', 'KG', 25),
        ('AMARILLO AMARILLO', 'KG', 300), ('ROJO ROJO', 'KG', 300),
        ('NEGRO NEGRO', 'KG', 300), ('VERDE VERDE', 'KG', 100),
        ('IBK-2', 'KG', 200), ('E1', 'KG', 3000), ('B1', 'KG', 300),
        ('B2', 'KG', 300), ('TAMBOR VERDE', 'KG', 200),
        ('BOLSAS TRANSPARENTES', 'UNIDAD', 2000), ('BOLSAS ROJAS', 'UNIDAD', 500),
        ('BOLSAS VERDES', 'UNIDAD', 500), ('BOLSAS AMARILLAS', 'UNIDAD', 500),
        ('POL1', 'KG', 10), ('POL2', 'KG', 10), ('ECN', 'KG', 200),
        ('ESPESOL', 'KG', 25), ('H1', 'KG', 25), ('HB', 'KG', 25),
        ('L80', 'KG', 50), ('MATIZ', 'KG', 25), ('MCZ1', 'KG', 25), ('UF', 'KG', 25),
    ]
    for nombre, unidad, stock_min in materiales_iniciales:
        if not Material.query.filter_by(nombre=nombre).first():
            db.session.add(Material(nombre=nombre, unidad=unidad, stock_minimo=stock_min))

    db.session.commit()


# Inicializar DB siempre (funciona con Gunicorn y con python app.py)
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
