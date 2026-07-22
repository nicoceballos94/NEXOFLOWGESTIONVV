# design-inbox

Bandeja de entrada para exports nuevos de Claude Design. **Nada de acá es código
de producción**: es referencia visual hasta que se promueva a `../design/`.

Cada cambio va en su subcarpeta con fecha y nombre descriptivo:

```
design-inbox/
└── 2026-07-10-header-mobile/
    ├── Ceibo RRHH.dc.html      # export bajado con DesignSync
    └── notas.md                # opcional: plantilla completada (docs/design-change-template.md)
```

Proceso completo: `../docs/design-change-intake.md`.

Una vez promovido y commiteado el cambio, la subcarpeta puede eliminarse
(el historial queda en git).
