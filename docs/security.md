# Security guide

Resumen en español al final / Spanish summary at the end.

## Threat model

- The router never runs anything it downloads. `mbl-update` fetches `routeros-<variant>.txt` over
  HTTPS with `check-certificate=yes`, reads it as plain data, validates every line (IPv4/IPv6 or
  CIDR with an allowed prefix) and only adds addresses to an address list. It never imports or
  executes the file.
- What a compromised publisher account could do: publish a fake list. The worst outcome is
  blocking addresses (for example your DNS resolver or a service you use) or dropping the list
  to nothing. It cannot run code on your router.
- Built-in limits on that: entry-count bounds, no drop above 50 % and no growth above 2x between
  builds, a minimum entry count at load time, a cap on how much of the list the allowlist may
  remove, and a router-side allowlist (`mbl-allow`) that always wins. The GitHub download range
  and public DNS are never blocked.
- Residual risk: a malicious but well-formed list inside those limits. Keep `mbl-allow` entries
  for what you cannot lose.

## What you should do on GitHub (maintainers and forks)

1. **Two-factor authentication** on every account with write access:
   <https://github.com/settings/security>.
2. **Protect `main`** with a ruleset (or branch protection): pull request required, and the status
   checks `test` and `e2e` required:
   <https://github.com/Psycomy/MikrotikBlockList/settings/rules>.
3. **Actions permissions**: default workflow token `read`; only the `publish` job gets write
   access. Also limit which workflows may run and who can trigger them:
   <https://github.com/Psycomy/MikrotikBlockList/settings/actions>.
4. **Review tokens**: revoke personal access tokens you no longer use:
   <https://github.com/settings/tokens>.
5. **Review deploy keys**: remove any you do not recognise:
   <https://github.com/Psycomy/MikrotikBlockList/settings/keys>.

## Reporting a vulnerability

Use GitHub private vulnerability reporting:
<https://github.com/Psycomy/MikrotikBlockList/security/advisories/new>.
Please do not open a public issue for security problems.

## Resumen en español

- El router no ejecuta nada de lo que descarga: solo lee datos, valida cada línea y añade
  direcciones a una lista. Una cuenta comprometida solo podría publicar listas falsas, es decir,
  bloquear IPs (o vaciar la lista), nunca ejecutar código en tu router. Los límites de tamaño, la
  caída del 50 %, el crecimiento de 2x, el tope de la allowlist y tu `mbl-allow` reducen ese riesgo.
- En GitHub: activa 2FA, protege `main` (PR obligatorio y estados `test` y `e2e` requeridos),
  deja los permisos de Actions en solo lectura (salvo `publish`), restringe quién puede lanzar
  workflows y revisa tokens y *deploy keys* (enlaces arriba).
- Para informar de una vulnerabilidad, usa el informe privado de GitHub (enlace arriba), no una
  incidencia pública.
