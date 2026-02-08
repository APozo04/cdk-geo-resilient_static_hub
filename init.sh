#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Este script debe ejecutarse con 'source' para que el entorno virtual se active correctamente:"
    echo "source ./init.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/venv"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

CREATED=false

# Crear entorno virtual si no existe
if [ ! -d "$VENV_DIR" ]; then
    echo "Creando entorno virtual en $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    CREATED=true
fi

# Activar el entorno virtual
source "$VENV_DIR/bin/activate"

# Solo instalar requirements si el entorno se acaba de crear
if [ "$CREATED" = true ]; then
    if [ -f "$REQUIREMENTS" ]; then
        echo "Instalando dependencias desde requirements.txt"
        pip install --upgrade pip >/dev/null
        pip install -r "$REQUIREMENTS"
    else
        echo "No se encontró el archivo requirements.txt"
    fi
fi

echo "Entorno virtual activado. Escribe 'deactivate' para salir."