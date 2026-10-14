# A local IMAP server for development

You don't need a real mailbox to work on sync. Two options:

## 1. GreenMail (quickest)

```bash
docker compose --profile dev-imap up -d imap
```

- Ports: IMAP 3143 (plain) and 3993 (SSL, self-signed certificate), SMTP 3025.
- Any username and password are accepted. A mailbox is created the first time you log in to it.
- Fill it with realistic sample mail: RFQs with a PDF and a BOQ attachment, a Hindi/English
  enquiry, a forwarded enquiry, a newsletter, a supplier invoice, an order follow-up, and a reply
  in Sent.

  ```bash
  # app running in Docker
  docker compose run --rm api python -m scripts.seed_dev_mailbox --host imap
  # app running on your machine (developer mode)
  cd backend && uv run python -m scripts.seed_dev_mailbox
  ```

  Running it twice adds the mail twice. Restart the `imap` container for an empty mailbox.
- Connect it in the app with **Other (IMAP)**. Use email `sales@dcengineering.in` (the seeded
  mailbox) with any password, port `3993`, SSL. Then tick "Allow this server's certificate" when the
  certificate warning appears.
  - Server name `imap` when the app runs in Docker. Inside the containers, `localhost` means the
    container itself.
  - Server name `localhost` when the backend runs on your machine.

## 2. Dovecot laid out like cPanel (used for the live integration tests)

This setup reproduces what most Indian shared-hosting mail looks like: `INBOX.Sent` style folders,
no SPECIAL-USE flags, a self-signed certificate, and real authentication.

```bash
sudo apt-get install -y dovecot-imapd
sudo useradd -r -M -s /usr/sbin/nologin testmail
D=/srv/e2odc; sudo mkdir -p $D/mail /run/e2odc && sudo chown testmail:testmail $D/mail
cd $D && sudo openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 30 -subj "/CN=mail.selfsigned.test"
echo 'sales@dc.test:{PLAIN}app-password-123' | sudo tee $D/users
sudo tee $D/dovecot.conf <<CONF
protocols = imap
listen = 127.0.0.1
base_dir = /run/e2odc
log_path = $D/dovecot.log
ssl = yes
ssl_cert = <$D/cert.pem
ssl_key = <$D/key.pem
disable_plaintext_auth = no
auth_mechanisms = plain login
first_valid_uid = 1
passdb {
  driver = passwd-file
  args = scheme=PLAIN username_format=%u $D/users
}
userdb {
  driver = static
  args = uid=testmail gid=testmail home=$D/mail/%u
}
mail_location = maildir:~/Maildir
namespace inbox {
  inbox = yes
  separator = .
  prefix = INBOX.
}
service imap-login {
  inet_listener imap {
    port = 1143
  }
  inet_listener imaps {
    port = 1993
    ssl = yes
  }
}
CONF
sudo dovecot -c $D/dovecot.conf
```

Then run the live tests (they create and delete their own folders):

```bash
cd backend
E2O_IMAP_TEST="127.0.0.1:1993:1143:sales@dc.test:app-password-123" uv run pytest tests/test_imap_live.py
```
