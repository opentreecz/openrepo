# OpenWrt package Makefile for OpenRepo
# This creates a minimal OpenRepo package suitable for OpenWrt devices.
# Note: OpenWrt targets are typically resource-constrained; consider
# using the CLI tool only on OpenWrt and connecting to a full OpenRepo
# server hosted elsewhere.

include $(TOPDIR)/rules.mk

PKG_NAME:=openrepo-cli
PKG_VERSION:=0.0.0
PKG_RELEASE:=1

PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/opentreecz/openrepo.git
PKG_SOURCE_VERSION:=HEAD
PKG_SOURCE_SUBDIR:=$(PKG_NAME)-$(PKG_VERSION)

PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)

include $(INCLUDE_DIR)/package.mk

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

define Build/Compile
	# Nothing to compile - pure Python
endef

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

$(eval $(call BuildPackage,openrepo-cli))
