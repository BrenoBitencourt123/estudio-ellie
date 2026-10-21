"""Fonte de contexto visual persistente, independente do histórico do chat."""
from __future__ import annotations

import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Ficha(BaseModel):
    model_config = ConfigDict(extra='forbid')
    publico: str = Field(default='', max_length=400)
    restricoes: list[str] = Field(default_factory=list, max_length=20)
    criterios: list[str] = Field(default_factory=list, max_length=20)
    audio: Literal['indefinido', 'silencioso', 'original', 'narracao'] = 'indefinido'


class Referencia(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,60}$')
    asset: dict
    papel: Literal['inspiracao', 'luz', 'composicao', 'personagem', 'cenario', 'roupa', 'movimento'] = 'inspiracao'
    orientacao: str = Field(default='', max_length=600)
    cenas: list[str] = Field(default_factory=list, max_length=12)
    ativa: bool = True


def chave(asset: dict) -> str:
    return hashlib.sha256(f"{asset['pasta']}/{asset['nome']}".encode()).hexdigest()[:20]


def referencias(p: dict) -> list[dict]:
    """Migração sem perda: anexos antigos permanecem visíveis, mas não são adotados sem seleção."""
    if 'referencias_criativas' in p:
        return p['referencias_criativas']
    itens = {}
    for m in p.get('mensagens', []):
        for a in m.get('anexos', []):
            if a.get('pasta') != 'saida':
                itens[chave(a)] = Referencia(id=chave(a), asset=a, ativa=False).model_dump()
    return list(itens.values())[-48:]


def selecionadas(p: dict, cena: str | None = None) -> list[dict]:
    return [r for r in referencias(p) if r['ativa'] and (cena is None or not r['cenas'] or cena in r['cenas'])]


def ficha_atual(p: dict) -> dict:
    return {**Ficha(**(p.get('ficha') or {})).model_dump(),
            'direcao': p.get('direcao') or {},
            'referencias': referencias(p),
            'cenas': [{**{k: s.get(k) for k in ('id', 'titulo', 'descricao', 'intencao', 'fala', 'exigencias', 'duracao', 'prompt', 'imagens')},
                       # o que a conferência disse do quadro atual (a IA não pode tratar quadro reprovado como pronto)
                       'conferencia_quadro': {k: (p.get('conferencias') or {}).get(s['id'], {}).get(k)
                                              for k in ('atende', 'resumo', 'aceita')}}
                      for s in p.get('tomadas', [])]}


def assinatura_revisao(p: dict) -> str:
    dados = {k: p.get(k) for k in ('direcao', 'ficha', 'cortes', 'duracao_final', 'master')}
    dados['referencias'] = selecionadas(p)
    dados['cenas'] = [{k: s.get(k) for k in ('id', 'titulo', 'descricao', 'intencao', 'exigencias', 'prompt', 'imagens', 'tipo', 'movimento_local', 'duracao', 'modo', 'modelo', 'resolucao')}
                      for s in p.get('tomadas', [])]
    dados['voz'] = {k: (p.get('narracao') or {}).get(k) for k in ('texto', 'audio', 'trilha')}
    return hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def revisao(p: dict) -> dict:
    assinatura = assinatura_revisao(p)
    return {'assinatura': assinatura, 'atual': (p.get('revisao') or {}).get('assinatura') == assinatura,
            'conferido_por': 'usuario' if (p.get('revisao') or {}).get('assinatura') == assinatura else None}
