# A local IMAP server for development

You don't need a real mailbox to work on sync. Two options:

## 1. GreenMail (quickest)

```bash
docker compose --profile dev-imap up -d imap
```

- IMAP `localhost:3143` (plain) and `localhost:3993` (SSL, self-signed certificate). SMTP is on `localhost:3025`.
- Any username and password are accepted. Mailboxes are created when you first log in.
- To connect it in the app, pick **Other (IMAP)** and enter server `localhost`, port `3993`, SSL. Then tick
  "Allow this server's certificate" when the certificate warning appears (it is self-signed).
- To put mail in it, send to `localhost:3025` over SMTP, or `APPEND` with any IMAP client. For example:

```python
import imaplib, time
c = imaplib.IMAP4("localhost", 3143); c.login("sales@example.com", "x")
c.create("Sent")
c.append("INBOX", None, imaplib.Time2Internaldate(time.time()),
         b"From: buyer@customer.com\r\nSubject: RFQ for flanges\r\n\r\nPlease quote 100 nos.")
```

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
