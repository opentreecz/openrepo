# OpenWrt package Makefile for OpenRepo
# Provides two packages:
#   - openrepo-cli: Lightweight CLI client (pure Python, arch-independent)
#   - openrepo-server: Full repository server with bundled dependencies
#
# The server package uses OPENREPO_USE_PYTHON_TOOLS=1 to generate
# Debian Packages/Packages.gz and RPM repomd.xml using pure-Python
# implementations instead of apt-ftparchive/createrepo_c (which are
# not available on OpenWrt).
#
# Minimum requirements for openrepo-server:
#   - 256 MB RAM
#   - 128 MB flash/storage
#   - OpenWrt 23.05+ recommended

include $(TOPDIR)/rules.mk

PKG_NAME:=openrepo
PKG_VERSION:=2.2.0
PKG_RELEASE:=1

PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/opentreecz/openrepo.git
PKG_SOURCE_VERSION:=v$(PKG_VERSION)
PKG_SOURCE_SUBDIR:=$(PKG_NAME)-$(PKG_VERSION)

PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)

include $(INCLUDE_DIR)/package.mk

# =============================================================================
# Package: openrepo-cli (lightweight CLI client)
# =============================================================================
define Package/openrepo-cli
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=OpenRepo CLI client
  URL:=https://github.com/opentreecz/openrepo
  DEPENDS:=+python3 +python3-requests
  PKGARCH:=all
endef

define Package/openrepo-cli/description
  Command-line client for OpenRepo package repository management server.
  Allows uploading, listing, copying, and managing packages in remote
  OpenRepo instances from CI/CD pipelines or command line.
endef

# =============================================================================
# Package: openrepo-server (full self-contained repository server)
# =============================================================================
define Package/openrepo-server
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=Web Servers/Proxies
  TITLE:=OpenRepo package repository server
  URL:=https://github.com/opentreecz/openrepo
  DEPENDS:=+python3 +python3-pip +python3-setuptools +python3-openssl \
           +python3-sqlite3 +nginx-ssl +gnupg +sqlite3-cli
  PKGARCH:=all
endef

define Package/openrepo-server/description
  Self-contained OpenRepo package repository server for OpenWrt.
  Hosts Debian APT, Red Hat RPM, and generic file repositories.
  Uses pure-Python tools for metadata generation (no apt-ftparchive
  or createrepo_c required). Requires minimum 256MB RAM, 128MB storage.
  Manages services via procd.
endef

# =============================================================================
# Build
# =============================================================================
define Build/Compile
	# Nothing to compile - pure Python application
endef

# =============================================================================
# Install: openrepo-cli
# =============================================================================
define Package/openrepo-cli/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_DIR) $(1)/usr/lib/python3/openrepo_cli

	# Install CLI module
	$(CP) $(PKG_BUILD_DIR)/cli/openrepo_cli/*.py $(1)/usr/lib/python3/openrepo_cli/
	$(CP) $(PKG_BUILD_DIR)/cli/main.py $(1)/usr/lib/python3/openrepo_cli/__main__.py

	# Create wrapper script
	echo '#!/bin/sh' > $(1)/usr/bin/openrepo
	echo 'exec python3 -m openrepo_cli "$$@"' >> $(1)/usr/bin/openrepo
	chmod +x $(1)/usr/bin/openrepo
endef

# =============================================================================
# Install: openrepo-server
# =============================================================================
define Package/openrepo-server/install
	$(INSTALL_DIR) $(1)/opt/openrepo
	$(INSTALL_DIR) $(1)/opt/openrepo/data/storage
	$(INSTALL_DIR) $(1)/opt/openrepo/data/repos
	$(INSTALL_DIR) $(1)/opt/openrepo/data/keyring
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_DIR) $(1)/etc/nginx/conf.d

	# Install Django application
	$(CP) $(PKG_BUILD_DIR)/web/*.py $(1)/opt/openrepo/
	$(CP) $(PKG_BUILD_DIR)/web/openrepo $(1)/opt/openrepo/openrepo
	$(CP) $(PKG_BUILD_DIR)/web/repo $(1)/opt/openrepo/repo
	$(CP) $(PKG_BUILD_DIR)/web/adapters $(1)/opt/openrepo/adapters
	$(CP) $(PKG_BUILD_DIR)/web/requirements.txt $(1)/opt/openrepo/

	# Install procd init script
	$(INSTALL_BIN) ./openrepo.init $(1)/etc/init.d/openrepo

	# Install UCI config
	$(INSTALL_CONF) ./files/openrepo.conf $(1)/etc/config/openrepo

	# Install nginx config
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/deploy/nginx/nginx.conf.prod \
		$(1)/etc/nginx/conf.d/openrepo.conf
endef

define Package/openrepo-server/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] && exit 0

# Create Python virtual environment and install dependencies
if [ ! -d /opt/openrepo/venv ]; then
    python3 -m venv /opt/openrepo/venv
    /opt/openrepo/venv/bin/pip install --no-cache-dir \
        django djangorestframework django-filter gunicorn gevent rpmfile
fi

# Run migrations
cd /opt/openrepo
export OPENREPO_USE_PYTHON_TOOLS=1
export OPENREPO_VAR_DIR=/opt/openrepo/data/
export OPENREPO_DB_TYPE=sqlite
/opt/openrepo/venv/bin/python manage.py migrate --noinput 2>/dev/null

echo "OpenRepo server installed. Enable with: /etc/init.d/openrepo enable && /etc/init.d/openrepo start"
endef

$(eval $(call BuildPackage,openrepo-cli))
$(eval $(call BuildPackage,openrepo-server))
