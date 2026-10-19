# Mage

A engine dos jogos acessíveis do R36S (Luma/ArkOS).

Cria, roda, confere e exporta jogos acessíveis feitos com o
[Mage Core](https://github.com/gogabs/r36s-a11y-sdk), o núcleo da engine:
um zip para o cartão do R36S e um `.exe` para Windows que abre sem instalar
nada.

*Mage creates, runs, checks and exports accessible audio games built with
Mage Core, its core library, for the R36S handheld (Luma/ArkOS) and Windows.
Docs are in Brazilian Portuguese.*

Tudo aqui é opcional: um `main.py` com a pasta `r36s_a11y` ao lado continua
sendo um jogo completo, sem a engine. A engine cuida do resto, pela linha
de comando ou pelo editor no navegador, que usam as mesmas peças.

Precisa de Python 3.7 ou mais novo, e nada além da biblioteca padrão.

## Começando

```bat
git clone https://github.com/gogabs/mage
cd mage
python mage.py new C:\jogos\corrida-de-sapos --name "Corrida de Sapos"
python mage.py run C:\jogos\corrida-de-sapos
python mage.py export C:\jogos\corrida-de-sapos
```

O jogo novo já roda e fala: espaço toca um bip, Tab repete as instruções e
Esc sai (no R36S, B, Select e A). O código você edita no editor que preferir
(VS Code, Notepad++...); a engine só cuida do projeto.

| Comando | O que faz |
|---|---|
| `new <pasta> [--name] [--author]` | Cria o jogo a partir do modelo: `game.json` com ações, `main.py`, um bip em `sounds/` e a cópia do `r36s_a11y`. O nome da pasta vira o id |
| `run [pasta] [--pc]` | Abre o jogo. No Windows, baixa as DLLs na primeira vez. No Linux, `--pc` abre a janela em vez de ler o controle do R36S |
| `check [pasta]` | Confere o `game.json`, as ações e os nomes dos arquivos, e mostra todos os problemas de uma vez |
| `update [pasta]` | Troca a cópia do `r36s_a11y` do jogo pela que vem com a engine, sem apagar as DLLs |
| `export [pasta] [--to r36s\|windows\|all]` | Gera em `dist/` o jogo pronto para cada plataforma |
| `editor [pasta]` | Abre o editor no navegador (veja abaixo) |

Sem pasta, os comandos usam a pasta atual.

## O editor

```bat
python mage.py editor C:\jogos\corrida-de-sapos
python mage.py editor          :: começa pela tela de criar ou abrir um jogo
```

O editor abre no navegador uma página servida só para este computador. Ela é
feita para leitor de tela: títulos para pular entre as seções, cada campo com
rótulo e dica, e um aviso falado depois de cada botão. Funciona sem
JavaScript. Pela página dá para:

- criar um jogo novo ou abrir um que já existe (os últimos ficam na tela inicial);
- editar o nome, a descrição, a versão, o autor, os idiomas e as tags;
- editar as ações: o botão do R36S, as teclas, o botão do controle e o do
  mouse de cada uma, criar ações novas e remover as que sobraram;
- ouvir os sons da pasta `sounds`;
- rodar o jogo, conferir o projeto e exportar;
- abrir o projeto no editor de código (o VS Code, se estiver instalado, ou o
  que você escolher nas preferências) e abrir a pasta do jogo.

Tudo o que o editor muda fica no `game.json`, então dá para alternar entre o
editor, a linha de comando e o editor de código à vontade. Para fechar, Ctrl+C
no terminal. As preferências ficam em `%APPDATA%\mage\editor.json` (ou
`~/.config/mage/editor.json`).

## O projeto

Um projeto é a pasta do jogo, no formato do
[contrato da plataforma](https://github.com/gogabs/r36s-a11y-sdk/blob/main/docs/contrato.md):

```
corrida-de-sapos/
  game.json
  main.py
  r36s_a11y/     a cópia do Mage Core que o jogo usa
  sounds/
```

### Ações no game.json

As ações ficam no `game.json`, e o `Game()` do Mage Core as registra sozinho, no
mesmo formato de `game.actions`:

```json
"actions": {
  "bip": {"r36s": "b", "key": ["space", "return"]},
  "sair": {"r36s": "a", "key": "escape"}
}
```

Assim dá para trocar teclas sem mexer no código. `game.label("bip")` diz o
nome no dispositivo em uso: "espaço" no teclado, "B" no R36S, "A" no Xbox.

## Exportar

- **R36S**: `dist/<id>-r36s.zip`, com a pasta `<id>` para copiar em
  `a11y/games` no cartão.
- **Windows**: `dist/<id>-windows.zip`, com a pasta do jogo e o
  `<Nome do Jogo>.exe`. Quem joga só descompacta e abre o `.exe`, sem instalar
  Python. Dentro vai o Python 3.13 oficial (do pacote NuGet da Python Software
  Foundation), isolado do Python do computador, as DLLs do Mage Core e o jogo, na
  pasta `jogo`. Os saves e o log (`<id>.log`, com o erro se o jogo fechar com
  erro) ficam em `%APPDATA%\r36s-a11y\<id>`.

A exportação deixa de fora o que é de desenvolvimento: `.git`, `tests`,
`tools`, `docs`, `dist` e `previews` da raiz, `__pycache__` e as DLLs (no
R36S). Para deixar outras coisas de fora:

```json
"export": {"ignore": ["rascunhos", "*.psd", "/notas.txt"]}
```

Um padrão sem `/` vale em qualquer pasta, com `/` no começo só na raiz do
jogo, e com `/` no meio para o caminho inteiro (`sounds/velhos`).

Como o cartão do R36S é exFAT, a exportação recusa links simbólicos, nomes
com `< > : " \ | ? *` e dois arquivos cujo nome só muda em maiúsculas.

Os downloads (DLLs e Python) são conferidos pelo SHA-256 e guardados em
`%LOCALAPPDATA%\r36s-a11y\downloads` (ou `~/.cache/r36s-a11y/downloads`),
então só a primeira exportação baixa. A exportação para Windows funciona a
partir de qualquer sistema, porque nada é compilado.

### Como o .exe funciona

O `.exe` é o `pythonw.exe` oficial renomeado. O `python313._pth` ao lado
isola esse Python do instalado no computador e faz ele importar o
`sitecustomize.py`, que abre `jogo/main.py`, manda a saída para o log e
avisa numa caixa de mensagem se o jogo fechar com erro.

## A versão do Mage Core

A engine traz a cópia do `r36s_a11y` que vai para os jogos em
`mage/sdk/`, numa versão fixa: um jogo exportado leva sempre o Mage Core
com que foi testado. `mage/sdk/origin.json` diz a versão e o commit. Para
trazer um Mage Core mais novo:

```bash
python tools/sync_sdk.py ../r36s-a11y-sdk
python -m unittest discover -s tests
```

Depois, `python mage.py update <pasta>` leva o Mage Core novo para cada jogo.

## Testes

```bash
python -m unittest discover -s tests
```
