# Tiny Stack

ICARUSのインストール済みゲームデータから独立生成する、設定生成式の軽量スタックMODです。
Caramel Stack size Plusのファイルやデータは使用していません。

## 変更対象

- 元から2個以上スタックできるアイテムの `MaxStack`
- 元からスタック不可の装備品・道具は変更しない
- チェスト、棚、バッグ、プレイヤーインベントリの枠数は変更しない
- タンク、容器、燃料、バッテリー容量は変更しない
- ゲーム起動中に設定を読み込む処理は持たない

変更するデータテーブルは `Traits/D_Itemable.json` の `MaxStack` だけです。
収納枠を管理するデータテーブルには触れません。

## 設定

`stack-config.json` を編集してから再ビルドします。

```json
{
  "global": {
    "mode": "multiplier",
    "value": 5,
    "cap": 9999
  },
  "individual": {
    "Item_Wood": 800,
    "Item_Stone": 600
  }
}
```

`global.mode` は次の2種類です。

- `multiplier`: 元のスタック数に `value` を掛ける
- `fixed`: 元からスタック可能な全アイテムを `value` に揃える

`individual` にICARUS内部アイテムIDと希望値を書くと、全体設定より優先されます。
存在しないIDやスタック不可アイテムを指定すると、誤設定防止のためビルドを中止します。

利用可能なID・元の値・適用後の値は、ビルド後に生成される
`dist/item-catalog.json` で確認できます。

## ビルド

`build_mod.py` は現在インストールされているICARUSの `data.pak` を展開し、
最新の `D_Itemable.json` からPAKとEXMODZを生成します。

```powershell
python .\build_mod.py
```

生成物は `dist` フォルダに出力されます。

- `Tiny_Stack_P.pak`: そのままゲームへ導入できるファイル
- `Tiny_Stack.EXMODZ`: JimK72 Icarus Mod Manager用
- `build-manifest.json`: ビルド条件と変更件数
- `item-catalog.json`: 個別指定に使えるアイテムID一覧

設定変更後は `build_mod.py` を再実行し、生成されたPAKを入れ直します。
設定ファイルはゲーム実行中には読み込まれないため、ゲーム内の処理負荷は増えません。

## 導入

他のスタック数変更MODを外してから、PAKを次へコピーします。

`Icarus/Icarus/Content/Paks/mods/`

ICARUSのアップデートでアイテム定義が変更された場合は、ビルドスクリプトを再実行します。

## 実装資料

- JimK72 Icarus Mod ManagerのEXMOD形式
- ICARUS本体の `Content/Data/data.pak`
- EXMODの検証規則（AgentKush icarus-modinfo-validator）

Caramel Stack size Plusは参考ファイルとしても展開・流用していません。
