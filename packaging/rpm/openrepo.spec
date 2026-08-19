Name:           openrepo
Version:        %{?version}%{!?version:0.0.0}
Release:        1%{?dist}
Summary:        Web-based package repository management server

License:        AGPL-3.0-only
URL:            https://github.com/opentreecz/openrepo
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  nodejs >= 20
BuildRequires:  npm

Requires:       python3 >= 3.10
Requires:       nginx
Requires:       postgresql-server
Requires:       createrepo_c
Requires:       gnupg2
Requires:       python3-apt

%description
OpenRepo is a self-hosted web server for managing and hosting
Debian apt/deb, Red Hat rpm, and generic file repositories.
It provides a web UI, REST API, CLI tool, PGP signing,
multi-architecture support, retention policies, and package
promotion pipelines.

%prep
%setup -q

%build
# Build frontend
cd frontend
npm ci
npm run build
cd ..

# Create virtualenv
python3 -m venv %{buildroot}/opt/openrepo/venv
%{buildroot}/opt/openrepo/venv/bin/pip install --no-cache-dir -r web/requirements.txt

%install
# Install application
install -d %{buildroot}/opt/openrepo
cp -r web/* %{buildroot}/opt/openrepo/
cp -r frontend/dist %{buildroot}/opt/openrepo/frontend-dist

# Install systemd service files
install -d %{buildroot}%{_unitdir}
install -m 0644 packaging/systemd/openrepo-web.service %{buildroot}%{_unitdir}/
install -m 0644 packaging/systemd/openrepo-worker.service %{buildroot}%{_unitdir}/

# Install nginx config
install -d %{buildroot}/etc/nginx/conf.d
install -m 0644 deploy/nginx/nginx.conf.prod %{buildroot}/etc/nginx/conf.d/openrepo.conf

# Install default config
install -d %{buildroot}/etc/openrepo
install -m 0640 .env.example %{buildroot}/etc/openrepo/openrepo.env

# Create data directories
install -d %{buildroot}/var/lib/openrepo/storage
install -d %{buildroot}/var/lib/openrepo/repos
install -d %{buildroot}/var/lib/openrepo/keyring

%files
/opt/openrepo/
%config(noreplace) /etc/openrepo/openrepo.env
%config(noreplace) /etc/nginx/conf.d/openrepo.conf
%{_unitdir}/openrepo-web.service
%{_unitdir}/openrepo-worker.service
%dir /var/lib/openrepo
%dir /var/lib/openrepo/storage
%dir /var/lib/openrepo/repos
%dir /var/lib/openrepo/keyring

%post
%systemd_post openrepo-web.service openrepo-worker.service

%preun
%systemd_preun openrepo-web.service openrepo-worker.service

%postun
%systemd_postun_with_restart openrepo-web.service openrepo-worker.service

%changelog
* Mon Jan 01 2024 opentree.cz <info@opentree.cz> - 0.0.0-1
- Automated build from CI
