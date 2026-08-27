# Runbook operacional

## 1. Preparação

- Confirme matriz de compatibilidade entre PowerStoreOS, PPDM, DDOS e FOS.
- Configure DNS/NTP consistente e certificados TLS confiáveis.
- Crie contas de automação dedicadas.
- Confirme que o PowerStore já é um asset source do PPDM e que a descoberta funciona.
- Confirme que DDBoost está habilitado no PowerProtect DD.
- No Brocade, use o switch principal de cada fabric e confirme a cfg que deve ser ativada.

## 2. Subida do serviço

```bash
cp .env.example .env
# gerar uma chave longa e uma senha administrativa forte
docker compose up --build -d
docker compose ps
```

Faça backup do volume `sanflow_data`. Ele contém o banco e as credenciais cifradas; a restauração também exige o mesmo `APP_SECRET_KEY`.

## 3. Cadastro

### PowerStore

Cadastre o endpoint de gerenciamento, porta 443, usuário, TLS e todos os WWPNs FC target. Marque `fabric=A` ou `fabric=B` conforme a conectividade.

### Hosts

Cadastre o nome exatamente como deve aparecer no PowerStore, o sistema operacional e os WWPNs das HBAs. Se o host já existe, o `PowerStore host ID` elimina ambiguidades.

### Brocade

Cadastre um switch principal por fabric. Informe FID, cfg ativa e geração `9.1` ou `9.2` para selecionar a ação de commit correta.

### PPDM

Cadastre o endpoint/porta 8443. **Buscar Data Domains e rotinas** lê as opções no momento da mudança; nada é mantido como catálogo paralelo.

## 4. Primeira execução

1. Mantenha **Dry-run seguro** ligado.
2. Selecione storage, hosts e Brocades.
3. Sincronize as opções do PowerStore e do PPDM.
4. Prefira uma política PPDM existente já homologada.
5. Execute e abra o detalhe das seis etapas.
6. Valide zone names, membros, cfg, política, DD e retenção.
7. Em janela de mudança, repita em modo live.

## 5. Falhas

| Etapa | Ação recomendada |
| --- | --- |
| Validação | corrija tipo, fabric, role ou WWN no inventário |
| Criar LUN | confira espaço, appliance, policy IDs, TLS e conta PowerStore |
| Mapear host | confirme que o WWPN não pertence a outro host e revise `os_type` |
| Zoning | verifique FID, cfg, checksum concorrente e transação de ZoneDB aberta |
| PPDM | execute discovery do asset source PowerStore e confirme compatibilidade |
| Verificação | use os IDs do workflow para comparar nos consoles oficiais |

Não exclua automaticamente um volume após falha de zoning/PPDM. Determine primeiro se ele já está em uso ou visível no fabric.

## 6. Atualização e rollback do aplicativo

Faça backup do volume e da `.env`, construa a nova imagem e suba o Compose. Para voltar, use a tag anterior da imagem; não substitua nem remova o volume de dados.
