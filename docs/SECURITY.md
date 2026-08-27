# Segurança

## Credenciais

As senhas dos appliances são cifradas antes de entrar no SQLite. A chave Fernet é derivada de `APP_SECRET_KEY`, que deve ser fornecida por secret manager ou arquivo `.env` protegido. Tokens PowerStore, PPDM e Brocade só existem em memória durante a chamada.

O inventário Ansible é criado em diretório temporário, contém as credenciais necessárias e é removido ao fim. Tarefas sensíveis usam `no_log: true`.

## Recomendações de produção

- Publique a aplicação atrás de um reverse proxy HTTPS.
- Restrinja o acesso por rede administrativa, firewall e autenticação adicional do proxy, se necessário.
- Troque usuário/senha padrão e `APP_SECRET_KEY` antes da primeira subida.
- Use certificados assinados e mantenha `verify_ssl=true`.
- Aplique menor privilégio e rotação nas contas dos appliances.
- Proteja e teste a restauração do volume SQLite e do secret correspondente.
- Encaminhe logs e eventos de auditoria para o SIEM.
- Não exponha `/docs` fora da rede administrativa sem autenticação adicional.

## Limites atuais

- A aplicação possui uma conta administrativa configurada por ambiente; integre-a a um proxy/OIDC para múltiplos usuários.
- O SQLite é adequado a um único container. Para alta concorrência, migre o modelo para PostgreSQL.
- O modo live executa mudanças reais após confirmação na interface. Aprovações ITSM devem envolver o endpoint antes de chamar `/api/workflows`.

## Reporte

Não abra uma issue pública contendo endereços, WWNs reais, logs com tokens ou credenciais. Remova dados sensíveis antes de compartilhar diagnósticos.
