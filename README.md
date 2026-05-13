# 📦 Sistema de Gestión de Bodega — Concretcol SAS

Aplicación web para registrar **entradas**, **reempaques** y **salidas** de materiales en bodega, con control de inventario en tiempo real y reportes por período.

---

## ✨ Funcionalidades

| Módulo | Descripción |
|---|---|
| **Dashboard** | Resumen del día: entradas, reempaques, salidas y alertas de stock |
| **Entradas** | Registra materiales que llegan a la bodega |
| **Reempaques** | Registra el proceso de reempaque con tiempo de trabajo |
| **Salidas** | Registra materiales que salen de la bodega |
| **Inventario** | Vista del stock actual de todos los materiales |
| **Reportes** | Filtro por fechas con totales acumulados |
| **Admin > Materiales** | Gestión del catálogo de materiales |
| **Admin > Usuarios** | Gestión de usuarios del sistema |

---

## 👥 Roles de Usuario

| Rol | Permisos |
|---|---|
| **Operario** | Registra entradas, reempaques, salidas. Ve inventario y reportes. |
| **Administrador** | Todo lo anterior + crear/desactivar usuarios, agregar materiales, eliminar registros. |

---

## 🔐 Credenciales por defecto

> ⚠️ **Cambia estas contraseñas inmediatamente después de instalar.**

| Usuario | Contraseña | Rol |
|---|---|---|
| `admin` | `Admin@2025!` | Administrador |
| `operario` | `Operario@2025!` | Operario |

---

## 🚀 Instalación

### 1. Clonar el repositorio
```bash
git clone https://github.com/TU_USUARIO/bodega-concretcol.git
cd bodega-concretcol
```

### 2. Crear entorno virtual e instalar dependencias
```bash
python3 -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 3. Configurar variables de entorno
```bash
cp .env.example .env
# Edita .env y cambia SECRET_KEY por una clave segura:
# python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Iniciar la aplicación
```bash
python app.py
```
Abre http://localhost:5000 en tu navegador.

---

## 🏭 Despliegue en Producción (Linux)

### Con Gunicorn
```bash
gunicorn -c gunicorn.conf.py app:app
```

### Con systemd (servicio permanente)
```ini
# /etc/systemd/system/bodega.service
[Unit]
Description=Bodega Concretcol
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/bodega-concretcol
EnvironmentFile=/var/www/bodega-concretcol/.env
ExecStart=/var/www/bodega-concretcol/venv/bin/gunicorn -c gunicorn.conf.py app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable bodega
sudo systemctl start bodega
```

### Con Nginx como proxy inverso
```nginx
server {
    listen 80;
    server_name tu-dominio.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## 🔒 Medidas de Seguridad Implementadas

- ✅ **Contraseñas hasheadas** con PBKDF2-SHA256 + salt de 16 bytes
- ✅ **Protección CSRF** en todos los formularios (Flask-WTF)
- ✅ **Sanitización XSS** de todos los campos de texto (bleach)
- ✅ **Sesiones seguras** con `HttpOnly`, `SameSite=Lax`
- ✅ **Control de acceso por roles** (admin vs operario)
- ✅ **Validación de stock** antes de registrar reempaques y salidas
- ✅ **Timeout de sesión** a las 8 horas
- ✅ **Handlers de error** para 403, 404, 500
- ✅ **Logging** de inicios de sesión exitosos y fallidos
- ✅ **SECRET_KEY** via variable de entorno (no hardcodeada)

### Para producción, añade también:
- HTTPS con certificado SSL (Let's Encrypt + Certbot)
- Firewall (UFW): solo puertos 80, 443 y 22
- Backups diarios de `instance/bodega.db`

---

## 📁 Estructura del Proyecto

```
bodega-concretcol/
├── app.py                  # Aplicación principal (rutas, modelos, formularios)
├── requirements.txt        # Dependencias Python
├── gunicorn.conf.py        # Configuración para producción
├── .env.example            # Plantilla de variables de entorno
├── .gitignore
├── README.md
├── static/
│   ├── css/style.css
│   └── js/app.js
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── entradas.html
│   ├── reempaques.html
│   ├── salidas.html
│   ├── inventario.html
│   ├── reportes.html
│   ├── admin_usuarios.html
│   ├── admin_materiales.html
│   └── error.html
└── instance/               # Creada automáticamente — contiene bodega.db
```

---

## 💾 Base de Datos

SQLite (`instance/bodega.db`) — generada automáticamente al iniciar. Para migrar a PostgreSQL, cambia `SQLALCHEMY_DATABASE_URI` en `app.py`.

---

## 📤 Subir a GitHub

```bash
git init
git add .
git commit -m "feat: sistema de gestión de bodega Concretcol"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/bodega-concretcol.git
git push -u origin main
```
