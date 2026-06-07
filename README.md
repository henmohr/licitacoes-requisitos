# licitacoes-requisitos

MVP para analisar editais em PDF, extrair requisitos e publicar o resultado no GitHub Pages.

## Fluxo

1. Coloque os PDFs em `inputs/` ou use o botão `Enviar PDF` da página para abrir a tela de upload do GitHub na pasta `inputs/`.
2. Faça push para `main`.
3. O GitHub Actions executa `scripts/extract_requirements.py`.
4. O workflow gera `docs/data/requirements.json`, `docs/data/requirements.csv`, `docs/data/municipality_catalog.json` e `docs/data/municipality_catalog.csv`.
5. O GitHub Pages publica `docs/index.html`.

## Estrutura

- `inputs/`: PDFs enviados para processamento
- `data/raw/`: bases brutas de referência, como `munic_informatica.csv`
- `data/processed/`: dados normalizados e prontos para consulta
- `scripts/extract_requirements.py`: extrator com OCR, classificação heurística e comparação
- `docs/`: site estático publicado no Pages
- `.github/workflows/process.yml`: pipeline de build e deploy

## Execução local

```bash
python3 scripts/extract_requirements.py --input-dir inputs --output-dir docs
```

Se quiser testar com outro diretório:

```bash
python3 scripts/extract_requirements.py --input-dir /caminho/para/pdfs --output-dir /tmp/saida
```

## O que o MVP faz

- Extrai texto do PDF com `pdftotext`
- Faz OCR automático quando a página parece vazia ou escaneada
- Identifica frases com padrões de requisito
- Classifica de forma heurística em categorias como `tecnico`, `prazo`, `habilitacao` e `restricao`
- Detecta títulos de seção, inclusive blocos de tabela com cabeçalhos quebrados em mais de uma linha
- Extrai lotes de preços com item, descrição, quantidade, valor unitário e valor total
- Cataloga o município detectado em cada edital, cruza com a base municipal e mantém CNPJ e metadados do município
- Agrupa os softwares identificados
- Mostra um mapa do Brasil com os municípios catalogados, com filtro por estado e software
- Resume por seção e marca duplicatas exatas entre documentos
- Gera CSV para abrir no Excel ou importar em outras ferramentas
- Publica uma página estática focada em lotes, catálogo e mapa

## Limitações atuais

- A extração é heurística, não semântica completa.
- PDFs escaneados ainda dependem de OCR para boa qualidade.
- Tabelas muito complexas podem exigir ajustes adicionais.

## Próximo passo recomendado

Depois deste MVP, o melhor avanço é adicionar:

- OCR automático quando o PDF não tiver texto
- revisão manual dos requisitos extraídos
- exportação CSV/JSON por edital
- enriquecer o catálogo com mais fontes de contato por município
