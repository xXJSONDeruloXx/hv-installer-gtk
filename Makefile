PREFIX ?= /usr/local
PYTHON ?= python3
BINDIR := $(DESTDIR)$(PREFIX)/bin
DATADIR := $(DESTDIR)$(PREFIX)/share/applications

.PHONY: install uninstall test check release

install:
	install -Dm755 hv-installer-gui.py $(BINDIR)/hv-installer-gtk
	install -Dm644 data/hvinstaller.desktop $(DATADIR)/hvinstaller.desktop
	install -d $(DESTDIR)$(PREFIX)/share/hv-installer-gtk/cpuid_fault_emulation
	cp -R cpuid_fault_emulation/. $(DESTDIR)$(PREFIX)/share/hv-installer-gtk/cpuid_fault_emulation/
	@if [ -d build/release-assets/umipcompatd ]; then \
		install -Dm755 build/release-assets/umipcompatd/umipcompatd $(DESTDIR)$(PREFIX)/libexec/umipcompatd; \
		install -Dm644 build/release-assets/umipcompatd/umipcompatd.service $(DESTDIR)/etc/systemd/system/umipcompatd.service; \
		install -d $(DESTDIR)$(PREFIX)/share/hv-installer-gtk/umipcompatd; \
		cp build/release-assets/umipcompatd/LICENSE build/release-assets/umipcompatd/SOURCE build/release-assets/umipcompatd/umipcompatd-source.tar.gz $(DESTDIR)$(PREFIX)/share/hv-installer-gtk/umipcompatd/; \
	fi

uninstall:
	rm -f $(BINDIR)/hv-installer-gtk
	rm -f $(DATADIR)/hvinstaller.desktop
	rm -rf $(DESTDIR)$(PREFIX)/share/hv-installer-gtk
	rm -f $(DESTDIR)$(PREFIX)/libexec/umipcompatd
	rm -f $(DESTDIR)/etc/systemd/system/umipcompatd.service

check:
	$(PYTHON) -m py_compile hv-installer-gui.py
	$(PYTHON) -m unittest discover -s tests -v

test: check

release: check
	$(PYTHON) packaging/build-umipcompatd.py
	$(PYTHON) packaging/build-release.py
