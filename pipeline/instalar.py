#!/usr/bin/env python3
"""Instala o comando `pipeline-analise` no sistema operacional.

  python3 instalar.py [--editavel] [--desinstalar]

Usa o instalador que existir, nesta ordem: pipx, uv (uv tool install) e pip (--user). Sem nenhum deles (Python sem pip), instala direto: copia o
pacote para a pasta de dados do usuário e cria o comando em ~/.local/bin (Linux/macOS) ou %USERPROFILE%\\.local\\bin (Windows, arquivo .cmd).
--editavel faz o comando usar o código desta pasta (alterações valem na hora; não mova a pasta depois)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
WINDOWS = os.name == 'nt'
BIN = Path.home() / '.local' / 'bin'
DADOS = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'pipeline-analise'


def com_instalador(editavel):
    if shutil.which('pipx'):
        return ['pipx', 'install', '--force'] + (['--editable'] if editavel else []) + [str(AQUI)]
    if shutil.which('uv'):
        return ['uv', 'tool', 'install', '--force'] + (['--editable'] if editavel else []) + [str(AQUI)]
    if subprocess.run([sys.executable, '-m', 'pip', '--version'], capture_output=True).returncode == 0:
        return [sys.executable, '-m', 'pip', 'install', '--user'] + (['-e'] if editavel else []) + [str(AQUI)]
    return None


def direto(editavel):
    origem = AQUI / 'src'
    if editavel:
        base = origem
    else:
        if DADOS.exists():
            shutil.rmtree(DADOS)
        shutil.copytree(origem / 'pipeline_analise', DADOS / 'pipeline_analise', ignore=shutil.ignore_patterns('__pycache__'))
        base = DADOS
    BIN.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        cmd = BIN / 'pipeline-analise.cmd'
        cmd.write_text(f'@echo off\r\nset PYTHONPATH={base};%PYTHONPATH%\r\n"{sys.executable}" -m pipeline_analise %*\r\n', encoding='utf-8')
    else:
        cmd = BIN / 'pipeline-analise'
        cmd.write_text(f'#!/bin/sh\nPYTHONPATH="{base}${{PYTHONPATH:+:$PYTHONPATH}}" exec "{sys.executable}" -m pipeline_analise "$@"\n', encoding='utf-8')
        cmd.chmod(0o755)
    print(f'comando instalado: {cmd} (pacote em {base})')
    if str(BIN) not in os.environ.get('PATH', '').split(os.pathsep):
        print(f'atenção: {BIN} não está no PATH; acrescente-o para chamar pipeline-analise de qualquer pasta')


def desinstalar():
    for f in (BIN / 'pipeline-analise', BIN / 'pipeline-analise.cmd'):
        if f.exists():
            f.unlink()
            print('removido', f)
    if DADOS.exists():
        shutil.rmtree(DADOS)
        print('removido', DADOS)


def main():
    if '--desinstalar' in sys.argv:
        desinstalar()
        return
    editavel = '--editavel' in sys.argv
    cmd = com_instalador(editavel)
    if cmd:
        print('$', ' '.join(cmd))
        sys.exit(subprocess.run(cmd).returncode)
    print('sem pipx, uv ou pip: instalação direta')
    direto(editavel)


if __name__ == '__main__':
    main()
