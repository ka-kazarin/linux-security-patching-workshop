# Vulnerability Management — учебный стенд (Slurm)

Стенд к вебинару-интенсиву по управлению уязвимостями (vulnerability management /
security patching). Полный жизненный цикл — сканирование, приоритизация, патчинг,
верификация, раскатка — на реальном многослойном стенде из двух дистрибутивов
(Ubuntu 26.04 LTS + Oracle Linux 9.6), оркестрация — Vagrant + Ansible + обычный
Makefile. Никакого скрытого CLI-фреймворка: каждый таргет печатает эхом реальную
команду, которую выполняет.

> **Статус:** репозиторий в разработке. Наполнение компонентов идёт по дорожной карте;
> этот README будет дополняться по мере готовности стенда.

## ⚠️ Изоляция эксплойтов

Стенд содержит **намеренно уязвимые** сервисы и рабочие эксплойты. Любой PoC
запускается **только внутри host-only сети стенда**, никогда против внешних систем.
Подробности и полный дисклеймер — в [`SECURITY.md`](../../SECURITY.md). Разворачивая
стенд, вы соглашаетесь с этими условиями.

## С чего начать

```bash
make help      # брендированная справка по всем командам
make doctor    # проверка готовности окружения перед запуском
make up-lite   # облегчённый стенд (2 VM, только stage) — для дома
make up        # полный стенд (4 VM: stage + prod)
```

По умолчанию `vagrant up` сам скачивает образы (`bento/ubuntu-26.04`,
`bento/oraclelinux-9`) с Vagrant Cloud. **Если Vagrant Cloud недоступен из вашей
сети** — скачайте образы заранее по ссылке и импортируйте локально, без обращения к
сети:

```bash
vagrant box add bento/ubuntu-26.04   /путь/к/скачанному/ubuntu-26.04.box   --provider virtualbox
vagrant box add bento/oraclelinux-9  /путь/к/скачанному/oraclelinux-9.box  --provider virtualbox
```

Имена (`bento/ubuntu-26.04`, `bento/oraclelinux-9`) должны совпадать с тем, что
указано в `stand/Vagrantfile` — тогда `vagrant up` увидит уже импортированный образ
и не полезет в сеть. Ссылка на образы: _будет добавлена_.

## Порядок демо (кратко)

1. `make scan-before` — скан уязвимостей (Trivy, через Ansible на живых VM).
2. `make patch ENV=stage` — патчинг ОС/middleware через Ansible.
3. `make verify` — pytest smoke: сервисы живы после патча (ничего не сломали).
   Доказательство, что CVE *закрыта*, даёт `make scan-after` и `make attack`,
   а не этот шаг.
4. `make scan-after` — уязвимости закрыты.
5. `make rollout` — раскатка на prod тем же плейбуком.
6. `make delta` — дельта сканов, выгрузка в реестр.

Живой эксплойт и виртуальный патч: `make attack` → `make waf-on` →
`make attack` (403) → `make patch-wordpress` (настоящий фикс) → `make waf-off`
→ `make attack` (эксплойт всё ещё мёртв — теперь пропатчено, а не просто прикрыто).

## Реестр находок (Google Sheets)

Живой реестр уязвимостей ведётся в шаблоне Google Sheets (вне репозитория):
_ссылка будет добавлена_.

## Документация

Теория вебинара — в отдельной презентации (вне этого репозитория). Здесь —
[`exercises.md`](exercises.md) с заданиями для самостоятельной проработки,
[`../../exploit/README.md`](../../exploit/README.md) — какую CVE
демонстрирует стенд и как воспроизвести атаку, и этот README — сценарий и
инструкция по использованию. Английская версия — в
[`../en/README.md`](../en/README.md).

## Стек

Vagrant · Ansible · Ubuntu 26.04 LTS · Oracle Linux 9.6 · Trivy ·
ModSecurity + OWASP CRS · pytest · Prometheus + Grafana · Docker Compose ·
WordPress (намеренно уязвимый)
