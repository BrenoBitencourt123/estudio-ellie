"""Direção criativa persistente e alterações pontuais no mapa de cenas."""
from __future__ import annotations

from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field


class Direcao(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ideia: str = Field(default='', max_length=600)
    objetivo: str = Field(default='', max_length=400)
    abertura: str = Field(default='', max_length=400)
    desenvolvimento: str = Field(default='', max_length=600)
    fecho: str = Field(default='', max_length=400)
    visual: str = Field(default='', max_length=400)
    audio: str = Field(default='', max_length=400)


def atualizar_direcao(atual: dict | None, mudancas: dict) -> dict:
    return Direcao(**{**(atual or {}), **mudancas}).model_dump()


def ajustar_plano(p: dict, ajustes: dict, campos_cena: set[str]) -> dict:
    """Atualiza cenas por ID, sem pedir à IA que reenvie o restante da produção.

    Incluir/remover/reordenar é explícito; um ID digitado errado nunca cria cena.
    A validação do plano completo continua no serviço de produção.
    """
    permitidos = {'layout', 'duracao_final', 'cortes', 'faixa', 'legenda', 'tomadas', 'remover', 'ordem'}
    if not isinstance(ajustes, dict) or set(ajustes) - permitidos:
        raise ValueError('O ajuste contém campos desconhecidos.')
    plano = {k: deepcopy(p.get(k)) for k in ('layout', 'duracao_final', 'tomadas', 'cortes', 'faixa', 'legenda')}
    for k in ('layout', 'duracao_final', 'cortes', 'legenda'):
        if k in ajustes:
            plano[k] = deepcopy(ajustes[k])
    if 'faixa' in ajustes:
        plano['faixa'] = {**(plano['faixa'] or {}), **ajustes['faixa']}
    cenas = plano['tomadas']
    estrutural = False
    alteradas = set()
    for patch in ajustes.get('tomadas', []):
        if not isinstance(patch, dict) or not patch.get('id'):
            raise ValueError('Cada ajuste de cena precisa do ID existente.')
        if set(patch) - campos_cena - {'nova'}:
            raise ValueError('O ajuste da cena contém campos desconhecidos.')
        if patch['id'] in alteradas:
            raise ValueError('Uma cena apareceu duas vezes no mesmo ajuste.')
        alteradas.add(patch['id'])
        atual = next((s for s in cenas if s['id'] == patch['id']), None)
        dados = {k: deepcopy(v) for k, v in patch.items() if k != 'nova'}
        if atual is None:
            if patch.get('nova') is not True:
                raise ValueError(f"Cena inexistente: {patch['id']}. Para adicionar, use nova=true.")
            cenas.append(dados)
            estrutural = True
        else:
            estrutural |= 'duracao' in dados and dados['duracao'] != atual['duracao']
            atual.update(dados)
    remover = ajustes.get('remover', [])
    if not set(remover).issubset({s['id'] for s in cenas}):
        raise ValueError('A remoção aponta para uma cena inexistente.')
    if remover:
        cenas = [s for s in cenas if s['id'] not in remover]
        estrutural = True
    if 'ordem' in ajustes:
        ordem = ajustes['ordem']
        if len(ordem) != len(cenas) or set(ordem) != {s['id'] for s in cenas}:
            raise ValueError('A ordem precisa conter cada cena uma única vez.')
        mapa = {s['id']: s for s in cenas}
        cenas = [mapa[id] for id in ordem]
        estrutural = True
    plano['tomadas'] = cenas
    if estrutural and 'cortes' not in ajustes:
        plano['cortes'] = []  # o serviço reconstrói os cortes na ordem escolhida
    return plano


def resumir_mudancas(antes: dict, depois: dict) -> list[str]:
    anteriores = {s['id']: s for s in antes.get('tomadas', [])}
    atuais = {s['id']: s for s in depois.get('tomadas', [])}
    linhas = []
    campos = {'descricao': 'ação visual', 'intencao': 'função na história', 'fala': 'fala prevista',
              'prompt': 'direção do movimento', 'tipo': 'forma de produzir', 'duracao': 'duração',
              'imagens': 'referências', 'titulo': 'nome'}
    for id, s in atuais.items():
        if id not in anteriores:
            linhas.append(f"Cena adicionada: {s['titulo']}.")
        else:
            mudados = [nome for k, nome in campos.items() if s.get(k, '') != anteriores[id].get(k, '')]
            if mudados:
                linhas.append(f"{s['titulo']}: {', '.join(mudados)}.")
    for id, s in anteriores.items():
        if id not in atuais:
            linhas.append(f"Cena removida: {s['titulo']}.")
    if list(anteriores) != list(atuais) and set(anteriores) == set(atuais):
        linhas.append('Ordem das cenas atualizada.')
    if antes.get('direcao') != depois.get('direcao'):
        linhas.append('Direção do vídeo atualizada.')
    return linhas[:14]
