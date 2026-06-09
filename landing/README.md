# Landing page — LATINOSPORT

Página de marketing estática (HTML + CSS, sin build ni dependencias). Basada en el
diseño hecho en Claude Design; el contenido se corrigió para reflejar el producto real.

## Archivos
- `index.html` — la página.
- `landing.css` — estilos.
- Fuentes (Space Grotesk / Hanken Grotesk) se cargan desde Google Fonts (requiere internet).

## Ver en local
```bash
cd landing
python -m http.server 8899
# abrir http://localhost:8899/index.html
```
(O simplemente abrir `index.html` en el navegador.)

## Pendiente de reemplazar antes de publicar
1. **URL del sistema** — los botones "Probar demo" e "Iniciar sesión" apuntan a `#contacto`
   / `#` como placeholder. Cambiar por la URL real del login/demo (busca `TODO` en `index.html`).
2. **WhatsApp** — número placeholder `59170000000` en los enlaces `wa.me/...` y en el footer
   (`+591 7000 0000`).
3. **Email** — `hola@snapcoding.bo`.
4. **Ciudad** — `Cochabamba, Bolivia`.
5. **Imágenes** — los bloques `.img-ph` (hero, cobranza, beneficios) son placeholders con
   borde punteado. Reemplazar cada uno por un `<img>` real, p. ej.:
   ```html
   <img class="mock-slot" src="capturas/panel.png" alt="Panel de LATINOSPORT">
   ```

## Notas de exactitud (qué promete vs. estado del producto)
- **Pago por QR**: el módulo existe; la pasarela (OpenBCB) corre hoy en sandbox. La entrega
  real requiere el contrato/credenciales del banco.
- **WhatsApp**: el envío real necesita una cuenta de Meta + plantillas aprobadas; hoy el
  backend está en modo mock. Los enlaces `wa.me` del landing sí funcionan (abren un chat).
