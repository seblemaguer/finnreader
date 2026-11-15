import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: root
    width: 1280; height: 900
    visible: true
    title: backend.title ? backend.title + " — FinnReader" : "FinnReader"

    // ---- palette ----
    readonly property color accent: "#00796b"
    readonly property color accentSoft: "#e0f2f1"
    readonly property color ink: "#1f2328"
    readonly property color muted: "#6b7280"
    readonly property color desk: "#e7e5e0"
    readonly property color surface: "#ffffff"
    readonly property color line: "#e3e1dc"
    Material.theme: Material.Light
    Material.accent: accent
    Material.primary: accent
    Material.foreground: ink
    color: desk

    // configuration lives in ~/.config/finnreader/config.yaml (read/written by the backend)
    readonly property var cfg: backend.config

    function zoomBy(step) { backend.saveConfig({ zoom: Math.min(1.0, Math.max(0.3, Math.round((cfg.zoom + step) * 10) / 10)) }) }
    function goToPage(p) {
        if (p < 0 || p >= backend.pageCount) return
        pageIndex = p
        pages.positionViewAtIndex(p, ListView.Beginning)
    }
    // the page being read: tracked explicitly so rotations and mode switches keep it
    property int pageIndex: 0
    onCurrentPageChanged: if (continuous && !renderTimer.running) pageIndex = currentPage
    readonly property bool continuous: cfg.continuous
    onContinuousChanged: Qt.callLater(() => goToPage(pageIndex))
    function keepPage() { if (!continuous) Qt.callLater(() => pages.positionViewAtIndex(pageIndex, ListView.Beginning)) }

    // ---- interactions: gesture -> action, from the config ----
    readonly property var ia: cfg.interactions
    function act(action, w, page) {
        switch (action) {
        case "translate":
            if (w) setCurrent(w, true)
            break
        case "mark":
            if (!w) break
            backend.toggleMark(w)
            selectedId = markByKey[w.key] ? markByKey[w.key].id : ""
            current = null; setCurrent(w, true)
            break
        case "previous_page": goToPage(page - 1); break
        case "next_page": goToPage(page + 1); break
        }
    }
    readonly property string hint: {
        const names = { hover: "hover", click: "click", double_click: "double-click" }
        const parts = Object.keys(names).filter(g => ia[g] && ia[g] !== "none").map(g => names[g] + " a word to " + ia[g])
        return parts.join(" · ") + (ia.hold_drag === "translate_area" ? " · hold and drag to translate an area" : "")
            + " · swipe or tap the margins to turn pages"
    }

    // ---- reading state ----
    property bool panelVisible: false   // reading first: the vocabulary panel starts hidden
    property var current: null          // word dict from backend.pageWords (+ page)
    property string currentTr: ""
    // the footer is for single words; an area's translation only shows in the bubble
    readonly property var footerWord: current && !current.key.startsWith("area:") ? current : null
    property var marks: backend.marks
    property var markByKey: {           // word key -> mark (a mark may span several words)
        let m = {}
        for (const x of marks) for (const k of x.keys) m[k] = x
        return m
    }
    readonly property var currentMark: current ? markByKey[current.key] || null : null
    // a marked word always shows its (possibly hand-fixed) translation
    readonly property string shownTr: (currentMark && currentMark.translation) || currentTr
    property string selectedId: ""      // marked word shown in the footer editor
    readonly property var selectedMark: marks.find(m => m.id === selectedId) || null
    readonly property int currentPage: Math.max(0, pages.indexAt(pages.width / 2, pages.contentY + pages.height / 3))
    readonly property real maxPageWidth: Math.max(1, ...backend.pageSizes.map(s => s[0]))
    readonly property real maxPageHeight: Math.max(1, ...backend.pageSizes.map(s => s[1]))
    // continuous: fit width; page by page: the whole page fits the view
    readonly property real fitZoom: continuous ? (pages.width - 48) / maxPageWidth
                                               : Math.min((pages.width - 48) / maxPageWidth, (pages.height - 24) / maxPageHeight)
    readonly property real zoom: Math.max(0.1, fitZoom * cfg.zoom)
    // Pages are rendered at renderZoom, which follows zoom only once it stops changing: a screen
    // rotation or window resize fires many width changes, each of which would re-render every page.
    // Meanwhile the existing bitmaps are just scaled.
    property real renderZoom: 0
    onZoomChanged: { renderTimer.restart(); keepPage() }
    Timer { id: renderTimer; interval: 300; onTriggered: root.renderZoom = root.zoom }

    // immediate: translate now (click); otherwise after the hover delay
    function setCurrent(w, immediate) {
        if (current && w && current.key === w.key) return
        current = w
        if (!w) { currentTr = ""; return }
        currentTr = backend.cached(w.lookup)
        if (currentTr || (markByKey[w.key] && markByKey[w.key].translation)) return
        if (immediate) backend.translate(w.lookup)
        else hoverTimer.restart()
    }

    Timer {
        id: hoverTimer
        interval: cfg.hover_delay
        onTriggered: if (root.current) backend.translate(root.current.lookup)
    }

    Connections {
        target: backend
        function onTranslated(word, tr) { if (root.current && root.current.lookup === word) root.currentTr = tr }
        function onMarksChanged() {  // a fixed translation applies to the word on screen at once
            if (!root.current) return
            root.currentTr = backend.cached(root.current.lookup)
            if (!root.currentTr) backend.translate(root.current.lookup)
        }
        function onMessage(msg) { toast.show(msg) }
        function onDocChanged() { root.current = null; root.selectedId = ""; root.pageIndex = 0; pages.positionViewAtBeginning() }
    }

    Component.onCompleted: {
        if (backend.pageCount === 0 && cfg.last_file) backend.open(cfg.last_file)
    }

    // ---- small building blocks ----
    component IconButton: ToolButton {
        property string iconName
        icon.source: "icons/" + iconName + ".svg"
        icon.width: 20; icon.height: 20
        icon.color: checked ? root.accent : root.ink
        display: AbstractButton.IconOnly
        ToolTip.visible: hovered && text !== ""
        ToolTip.delay: 600
        ToolTip.text: text
    }
    // compact text field: Material's tall outlined field with floating label is too heavy here
    component Field: TextField {
        id: fld
        property string hint
        placeholderText: text ? "" : hint
        topPadding: 8; bottomPadding: 8; leftPadding: 10; rightPadding: 10
        selectByMouse: true
        background: Rectangle { radius: 6; color: "#f6f5f2"; border.color: fld.activeFocus ? root.accent : root.line }
    }
    component Section: Label {
        font.pixelSize: 12; font.weight: Font.DemiBold; font.letterSpacing: 1
        color: root.accent
        topPadding: 14
        Layout.columnSpan: 2
    }

    // ---- toolbar ----
    header: ToolBar {
        height: 52
        background: Rectangle {
            color: root.surface
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8; anchors.rightMargin: 8
            spacing: 2

            IconButton { iconName: "open"; text: "Open PDF (Ctrl+O)"; onClicked: openDialog.open() }
            Label {
                text: backend.title || "FinnReader"
                font.pixelSize: 16; font.weight: Font.DemiBold
                elide: Text.ElideRight
                Layout.maximumWidth: 320
                leftPadding: 4
            }
            Item { Layout.fillWidth: true }

            // zoom
            IconButton { iconName: "zoom-out"; text: "Zoom out (Ctrl+-)"; enabled: backend.pageCount > 0; onClicked: root.zoomBy(-0.1) }
            Label { text: Math.round(cfg.zoom * 100) + "%"; color: root.muted; Layout.preferredWidth: 40; horizontalAlignment: Text.AlignHCenter }
            IconButton { iconName: "zoom-in"; text: "Zoom in (Ctrl++)"; enabled: backend.pageCount > 0; onClicked: root.zoomBy(0.1) }
            IconButton { iconName: "fit"; text: root.continuous ? "Fit width" : "Fit page"; enabled: backend.pageCount > 0; onClicked: backend.saveConfig({ zoom: 1.0 }) }
            IconButton {
                iconName: "scroll"; text: "Continuous scrolling"
                checkable: true; checked: root.continuous
                onToggled: backend.saveConfig({ continuous: checked })
            }
            ToolSeparator {}
            // page n / N, editable
            TextField {
                id: pageField
                enabled: backend.pageCount > 0
                text: backend.pageCount ? (root.continuous ? root.currentPage : root.pageIndex) + 1 : ""
                horizontalAlignment: Text.AlignHCenter
                validator: IntValidator { bottom: 1; top: Math.max(1, backend.pageCount) }
                Layout.preferredWidth: 48
                topPadding: 4; bottomPadding: 4
                background: Rectangle { radius: 6; color: "#f6f5f2"; border.color: pageField.activeFocus ? root.accent : root.line }
                onAccepted: { root.goToPage(parseInt(text) - 1); focus = false }
            }
            Label { text: "/ " + backend.pageCount; color: root.muted; visible: backend.pageCount > 0; rightPadding: 6 }
            Item { Layout.fillWidth: true }

            // language chip
            Rectangle {
                radius: 13; height: 26
                color: root.accentSoft
                Layout.preferredWidth: chip.implicitWidth + 20
                Label {
                    id: chip
                    anchors.centerIn: parent
                    text: cfg.source + " → " + cfg.target + "  ·  " + cfg.translators.join(", ")
                    color: root.accent; font.pixelSize: 12; font.weight: Font.Medium
                }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: settingsDialog.open() }
            }
            ToolSeparator {}
            IconButton {
                iconName: "import"; text: "Import highlights of the configured colour"
                enabled: backend.pageCount > 0 && !backend.busy
                onClicked: backend.importHighlights()
            }
            IconButton { iconName: "export"; text: "Export to " + cfg.export_format + " (Ctrl+E)"; enabled: backend.pageCount > 0; onClicked: backend.exportDocument() }
            IconButton {
                iconName: "panel"; text: "Vocabulary (" + root.marks.length + ")"
                checkable: true; checked: root.panelVisible; onToggled: root.panelVisible = checked
            }
            IconButton { iconName: "settings"; text: "Settings"; onClicked: settingsDialog.open() }
        }
    }

    Shortcut { sequences: [StandardKey.Open]; onActivated: openDialog.open() }
    Shortcut { sequences: [StandardKey.ZoomIn]; onActivated: root.zoomBy(0.1) }
    Shortcut { sequences: [StandardKey.ZoomOut]; onActivated: root.zoomBy(-0.1) }
    Shortcut { sequence: "Ctrl+E"; onActivated: backend.exportDocument() }
    Shortcut { sequence: "Escape"; onActivated: root.selectedId = "" }

    FileDialog {
        id: openDialog
        nameFilters: ["PDF, subtitles or video (*.pdf *.srt *.vtt *.ass *.ssa *.mkv *.mp4 *.webm *.avi *.mov)",
                      "PDF files (*.pdf)"]
        onAccepted: { backend.saveConfig({ last_file: selectedFile.toString() }); backend.open(selectedFile) }
    }

    SplitView {
        anchors.fill: parent
        handle: Rectangle { implicitWidth: 1; color: root.line }

        // ---- pages ----
        ListView {
            id: pages
            objectName: "pages"
            SplitView.fillWidth: true
            clip: true
            spacing: root.continuous ? 20 : 0
            interactive: root.continuous   // page by page: pages only move through the page actions
            model: backend.pageCount
            cacheBuffer: height   // one screen ahead/behind: fewer full-resolution renders
            header: Item { height: root.continuous ? 20 : 0 }
            footer: Item { height: root.continuous ? 20 : 0 }
            ScrollBar.vertical: ScrollBar { policy: root.continuous ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
            onHeightChanged: root.keepPage()
            Keys.onLeftPressed: root.goToPage(root.pageIndex - 1)
            Keys.onRightPressed: root.goToPage(root.pageIndex + 1)

            delegate: Item {
                id: pageItem
                required property int index
                readonly property var size: backend.pageSizes[index]
                readonly property var words: backend.pageWords(index)
                property int rev: 0   // bumped when the page's highlights change -> re-render
                width: ListView.view.width
                height: root.continuous ? size[1] * root.zoom : ListView.view.height

                Connections {
                    target: backend
                    function onPageModified(p) { if (p === pageItem.index) pageItem.rev++ }
                }

                // soft shadow
                Rectangle { x: paper.x - 1; y: paper.y + 1; width: paper.width + 2; height: paper.height + 2; radius: 3; color: "#14000000" }
                Rectangle { x: paper.x - 3; y: paper.y + 3; width: paper.width + 6; height: paper.height + 4; radius: 6; color: "#0a000000" }

                Item {
                    id: paper
                    width: pageItem.size[0] * root.zoom
                    height: pageItem.size[1] * root.zoom
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: (pageItem.height - height) / 2

                    Rectangle { anchors.fill: parent; color: "white" }
                    Image {
                        anchors.fill: parent
                        asynchronous: true
                        retainWhileLoading: true   // keep showing the old bitmap until the new one is ready
                        source: root.renderZoom > 0 ? "image://page/" + pageItem.index + "/" + (root.renderZoom * Screen.devicePixelRatio).toFixed(2) + "/" + pageItem.rev : ""
                    }

                    // word under the pointer
                    Rectangle {
                        id: hoverBox
                        readonly property var w: root.current && root.current.page === pageItem.index ? root.current : null
                        visible: w !== null
                        x: w ? w.x0 * root.zoom - 3 : 0; y: w ? w.y0 * root.zoom - 2 : 0
                        width: w ? (w.x1 - w.x0) * root.zoom + 6 : 0
                        height: w ? (w.y1 - w.y0) * root.zoom + 4 : 0
                        color: Qt.rgba(0, 0.47, 0.42, 0.08); border.color: root.accent; border.width: 1.5; radius: 4
                    }

                    // inline translation bubble: never takes input, disappears when the pointer moves on
                    Item {
                        id: bubbleBox
                        readonly property bool below: hoverBox.y - height - 8 < 0
                        visible: hoverBox.visible && root.shownTr !== ""
                        z: 10
                        width: bubble.width + 20; height: bubble.height + 10
                        x: Math.max(0, Math.min(paper.width - width, hoverBox.x + hoverBox.width / 2 - width / 2))
                        y: below ? hoverBox.y + hoverBox.height + 8 : hoverBox.y - height - 8
                        Rectangle {
                            width: 10; height: 10; rotation: 45; color: "#263238"
                            x: Math.max(6, Math.min(parent.width - 16, hoverBox.x + hoverBox.width / 2 - bubbleBox.x - 5))
                            y: bubbleBox.below ? -4 : parent.height - 6
                        }
                        Rectangle { anchors.fill: parent; color: "#263238"; radius: 6 }
                        Label {
                            id: bubble; anchors.centerIn: parent; text: root.shownTr; color: "white"; font.pixelSize: 15
                            width: Math.min(implicitWidth, paper.width - 40); wrapMode: Text.Wrap   // an area's translation can be long
                        }
                    }

                    // area being selected (hold and drag)
                    Rectangle {
                        id: selectionBox
                        visible: false
                        color: Qt.rgba(0, 0.47, 0.42, 0.12); border.color: root.accent; border.width: 1
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton
                    property real pressX; property real pressY; property double pressTime; property bool swiped
                    property bool selecting: false
                    pressAndHoldInterval: 400
                    preventStealing: selecting   // while selecting, a drag must not scroll the list
                    property real wheelSum: 0
                    function wordAt(mx, my) {
                        const x = (mx - paper.x) / root.zoom, y = (my - paper.y) / root.zoom
                        for (const w of pageItem.words)
                            if (x >= w.x0 - 1 && x <= w.x1 + 1 && y >= w.y0 && y <= w.y1)
                                return Object.assign({ page: pageItem.index }, w)
                        return null
                    }
                    // -1 left margin, +1 right margin, 0 elsewhere. Margins = outside the text column
                    // (or the outer 15% of an empty page); only ever used when no word is under the pointer.
                    function marginAt(mx) {
                        const x = (mx - paper.x) / root.zoom, ws = pageItem.words
                        const left = ws.length ? Math.min(...ws.map(w => w.x0)) - 2 : pageItem.size[0] * 0.15
                        const right = ws.length ? Math.max(...ws.map(w => w.x1)) + 2 : pageItem.size[0] * 0.85
                        return x < left ? -1 : x > right ? 1 : 0
                    }
                    function marginAction(mx) {
                        const dir = marginAt(mx)
                        return dir < 0 ? root.ia.left_margin_click : dir > 0 ? root.ia.right_margin_click : ""
                    }
                    // the selection rectangle, from the press point to (mx, my), in paper coordinates
                    function select(mx, my) {
                        selectionBox.x = Math.min(pressX, mx) - paper.x; selectionBox.y = Math.min(pressY, my) - paper.y
                        selectionBox.width = Math.abs(mx - pressX); selectionBox.height = Math.abs(my - pressY)
                    }
                    function startSelecting() {
                        selecting = true
                        select(pressX, pressY)
                        selectionBox.visible = true
                    }
                    onPressed: mouse => {
                        pages.forceActiveFocus()   // arrow keys turn pages; text fields keep their own arrows
                        pressX = mouse.x; pressY = mouse.y; pressTime = Date.now(); swiped = false
                        if ((mouse.modifiers & Qt.ShiftModifier) && root.ia.hold_drag === "translate_area") startSelecting()
                    }
                    onPressAndHold: if (root.ia.hold_drag === "translate_area" && !selecting) startSelecting()
                    onCanceled: { selecting = false; selectionBox.visible = false }
                    // a swipe: quick, mostly horizontal; finger moving left = swipe_left
                    onReleased: mouse => {
                        if (selecting) {
                            selecting = false; selectionBox.visible = false; swiped = true   // swiped: no click either
                            const z = root.zoom
                            const a = backend.area(pageItem.index, (pressX - paper.x) / z, (pressY - paper.y) / z,
                                                   (mouse.x - paper.x) / z, (mouse.y - paper.y) / z)
                            if (a.lookup) { root.current = null; root.setCurrent(a, true) }
                            return
                        }
                        const dx = mouse.x - pressX, dy = mouse.y - pressY
                        if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy) && Date.now() - pressTime < 800) {
                            swiped = true
                            root.act(dx < 0 ? root.ia.swipe_left : root.ia.swipe_right, null, pageItem.index)
                        }
                    }
                    onPositionChanged: mouse => {
                        if (selecting) { select(mouse.x, mouse.y); return }
                        if (pressed || root.ia.hover !== "translate") return
                        const w = wordAt(mouse.x, mouse.y)
                        if (w) root.setCurrent(w, false)
                    }
                    onClicked: mouse => {
                        if (swiped) return
                        const w = wordAt(mouse.x, mouse.y)
                        if (w) {
                            if (root.markByKey[w.key]) root.selectedId = root.markByKey[w.key].id
                            root.act(root.ia.click, w, pageItem.index)
                        } else if (marginAt(mouse.x)) {
                            root.act(marginAction(mouse.x), null, pageItem.index)
                        } else {
                            root.setCurrent(null)   // tap on blank paper dismisses the translation
                        }
                    }
                    onDoubleClicked: mouse => {
                        if (selecting) return
                        const w = wordAt(mouse.x, mouse.y)
                        if (w) root.act(root.ia.double_click, w, pageItem.index)
                        // 2nd tap of a fast double tap in the margin: turn again, from the page the 1st tap showed
                        else if (marginAt(mouse.x))
                            root.act(marginAction(mouse.x), null, root.continuous ? pages.indexAt(pages.width / 2, pages.contentY + 1) : root.pageIndex)
                    }
                    onExited: if (root.ia.hover === "translate") root.setCurrent(null)
                    // page by page: the wheel turns pages (touchpads send many small steps: sum them)
                    onWheel: wheel => {
                        if (root.continuous) { wheel.accepted = false; return }
                        wheelSum += wheel.angleDelta.y
                        if (Math.abs(wheelSum) >= 120) { root.goToPage(root.pageIndex + (wheelSum < 0 ? 1 : -1)); wheelSum = 0 }
                    }
                }
            }

            // empty state
            ColumnLayout {
                anchors.centerIn: parent
                visible: backend.pageCount === 0
                spacing: 14
                Image { source: "icons/book.svg"; sourceSize: Qt.size(56, 56); opacity: 0.35; Layout.alignment: Qt.AlignHCenter }
                Label { text: "Open a PDF to start reading"; font.pixelSize: 20; Layout.alignment: Qt.AlignHCenter }
                Label {
                    text: root.hint
                    color: root.muted; Layout.alignment: Qt.AlignHCenter
                }
                Button { text: "Open PDF"; highlighted: true; Layout.alignment: Qt.AlignHCenter; onClicked: openDialog.open() }
            }
        }

        // ---- vocabulary panel ----
        Pane {
            visible: root.panelVisible
            SplitView.preferredWidth: 340
            SplitView.minimumWidth: 240
            padding: 0
            Material.background: root.surface

            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: 12
                    Label { text: "Vocabulary"; font.pixelSize: 17; font.weight: Font.DemiBold }
                    Label { text: root.marks.length; color: root.muted }
                    Item { Layout.fillWidth: true }
                    IconButton { iconName: "close"; text: "Hide"; onClicked: root.panelVisible = false }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: root.line }

                ListView {
                    id: markList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: root.marks
                    ScrollBar.vertical: ScrollBar {}

                    Label {
                        anchors.centerIn: parent
                        visible: root.marks.length === 0
                        horizontalAlignment: Text.AlignHCenter
                        color: root.muted
                        text: "No marked words yet.\nDouble-click a word to mark it."
                    }

                    delegate: Rectangle {
                        id: item
                        required property var modelData
                        readonly property bool selected: modelData.id === root.selectedId
                        width: markList.width
                        height: col.implicitHeight + 16
                        color: selected ? root.accentSoft : (hover.hovered ? "#f6f5f2" : "transparent")
                        HoverHandler { id: hover }
                        TapHandler { onTapped: { root.selectedId = item.modelData.id; root.goToPage(item.modelData.page) } }
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }

                        ColumnLayout {
                            id: col
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 14; rightMargin: 6 }
                            spacing: 0
                            RowLayout {
                                Label { text: item.modelData.lookup; font.pixelSize: 15; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                                Label { text: "p. " + (item.modelData.page + 1); color: root.muted; font.pixelSize: 12 }
                                IconButton {
                                    iconName: "trash"; text: "Unmark"
                                    opacity: hover.hovered || item.selected ? 1 : 0
                                    icon.width: 16; icon.height: 16
                                    onClicked: backend.removeMark(item.modelData.id)
                                }
                            }
                            TextField {
                                Layout.fillWidth: true
                                Layout.rightMargin: 8
                                text: item.modelData.translation
                                id: trField
                                placeholderText: text ? "" : "translation…"
                                color: root.accent
                                topPadding: 4; bottomPadding: 4; leftPadding: 8
                                background: Rectangle { radius: 6; color: trField.activeFocus ? "white" : "transparent"; border.color: trField.activeFocus || trField.hovered ? root.line : "transparent" }
                                onEditingFinished: backend.setTranslation(item.modelData.id, text)
                            }
                        }
                    }
                }
            }
        }
    }

    // ---- footer: always-visible translation + editor of the selected marked word ----
    footer: Pane {
        padding: 0
        height: 60
        background: Rectangle {
            color: root.surface
            Rectangle { width: parent.width; height: 1; color: root.line }
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18; anchors.rightMargin: 10
            spacing: 12

            Label {
                text: root.footerWord ? root.footerWord.lookup : ""
                font.pixelSize: 19; font.weight: Font.DemiBold
                visible: root.footerWord !== null
            }
            Label {
                text: root.footerWord ? "→  " + (root.shownTr || "…") : root.hint
                font.pixelSize: root.footerWord ? 19 : 14
                color: root.footerWord ? root.accent : root.muted
                Layout.fillWidth: true
                elide: Text.ElideRight
            }

            // background work (import shows its progress here)
            RowLayout {
                visible: backend.busy !== ""
                BusyIndicator { running: parent.visible; Layout.preferredWidth: 28; Layout.preferredHeight: 28 }
                Label { text: backend.busy; color: root.muted }
            }

            // manual fix of a marked word's translation (select it with a click/tap or by marking it)
            Rectangle {
                visible: root.selectedMark !== null
                radius: 22; height: 44
                color: root.accentSoft
                Layout.preferredWidth: fixRow.implicitWidth + 24
                RowLayout {
                    id: fixRow
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left; anchors.leftMargin: 16
                    spacing: 8
                    Rectangle { width: 12; height: 12; radius: 3; color: cfg.highlight_color }
                    Label { text: root.selectedMark ? root.selectedMark.lookup : ""; font.weight: Font.DemiBold }
                    TextField {
                        id: fixField
                        Layout.preferredWidth: 240
                        text: root.selectedMark ? root.selectedMark.translation : ""
                        placeholderText: text ? "" : "fix the translation…"
                        selectByMouse: true
                        topPadding: 4; bottomPadding: 4
                        background: Rectangle { radius: 6; color: "white"; border.color: fixField.activeFocus ? root.accent : root.line }
                        leftPadding: 8; rightPadding: 8
                        onEditingFinished: if (root.selectedMark) backend.setTranslation(root.selectedId, text)
                        Keys.onEscapePressed: { text = root.selectedMark.translation; focus = false }
                    }
                    IconButton { iconName: "trash"; text: "Unmark"; icon.width: 16; icon.height: 16; onClicked: { backend.removeMark(root.selectedId); root.selectedId = "" } }
                    IconButton { iconName: "close"; text: "Close (Esc)"; icon.width: 16; icon.height: 16; onClicked: root.selectedId = "" }
                }
            }
        }
    }

    // ---- transient message, fades by itself ----
    Label {
        id: toast
        function show(msg) { text = msg; opacity = 1; toastTimer.restart() }
        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: 20 }
        z: 100; opacity: 0
        leftPadding: 18; rightPadding: 18; topPadding: 10; bottomPadding: 10
        color: "white"
        background: Rectangle { color: "#323232"; radius: height / 2 }
        Behavior on opacity { NumberAnimation { duration: 250 } }
        Timer { id: toastTimer; interval: 4000; onTriggered: toast.opacity = 0 }
    }

    // ---- settings ----
    ColorDialog {
        id: colorDialog
        onAccepted: colorSwatch.color = selectedColor
    }

    Dialog {
        id: settingsDialog
        objectName: "settingsDialog"
        title: "Settings"
        modal: true
        anchors.centerIn: parent
        width: Math.min(680, root.width - 40)
        height: Math.min(720, root.height - 40)
        standardButtons: Dialog.Save | Dialog.Cancel
        background: Rectangle { color: root.surface; radius: 14 }
        onAboutToShow: {   // not onOpened: that fires after the open animation, too late if Save is quick
            srcField.text = cfg.source; dstField.text = cfg.target
            enginesField.text = cfg.translators.join(", "); opusField.text = cfg.opus_model
            colorSwatch.color = cfg.highlight_color; opacitySlider.value = cfg.highlight_opacity
            delayBox.value = cfg.hover_delay; continuousSwitch.checked = cfg.continuous
            for (let i = 0; i < gestureRows.count; i++) gestureRows.itemAt(i).reset()
            formatCombo.currentIndex = Math.max(0, backend.exportFormats.indexOf(cfg.export_format))
        }
        function interactions() {
            const out = {}
            for (let i = 0; i < gestureRows.count; i++) out[gestureRows.itemAt(i).modelData] = gestureRows.itemAt(i).value
            return out
        }
        onAccepted: {
            backend.saveConfig({
                source: srcField.text.trim(), target: dstField.text.trim(),
                translators: enginesField.text.split(",").map(e => e.trim()).filter(e => e),
                opus_model: opusField.text.trim(),
                highlight_color: colorSwatch.color.toString(), highlight_opacity: opacitySlider.value,
                hover_delay: delayBox.value,
                continuous: continuousSwitch.checked, interactions: interactions(),
                export_format: formatCombo.currentText
            })
            if (root.current) { const w = root.current; root.current = null; root.setCurrent(w) }
        }

        ScrollView {
            objectName: "settingsScroll"
            anchors.fill: parent
            contentWidth: availableWidth
            GridLayout {
                width: parent.width
                columns: 2
                columnSpacing: 16
                rowSpacing: 6

                Section { text: "TRANSLATION"; topPadding: 0 }
                Label { text: "Languages" }
                RowLayout {
                    Layout.fillWidth: true
                    Field { id: srcField; hint: "fi"; Layout.preferredWidth: 80; horizontalAlignment: Text.AlignHCenter }
                    Label { text: "→"; color: root.muted }
                    Field { id: dstField; hint: "en"; Layout.preferredWidth: 80; horizontalAlignment: Text.AlignHCenter }
                }
                Label { text: "Translators" }
                Field {
                    id: enginesField; Layout.fillWidth: true
                    hint: "opus-mt, google, mymemory"
                    ToolTip.visible: hovered; ToolTip.delay: 500
                    ToolTip.text: "Tried in order until one succeeds. Available: " + backend.translatorNames.join(", ")
                }
                Label { text: "opus-mt model" }
                Field {
                    id: opusField; Layout.fillWidth: true
                    hint: backend.defaultOpusModel
                    ToolTip.visible: hovered; ToolTip.delay: 500
                    ToolTip.text: "Hugging Face model name or local directory; {SRC} and {TGT} are replaced by the languages."
                }

                Section { text: "HIGHLIGHT" }
                Label { text: "Colour" }
                RowLayout {
                    Layout.fillWidth: true
                    Rectangle {
                        id: colorSwatch
                        width: 36; height: 36; radius: 8
                        border.color: root.line; border.width: 1
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { colorDialog.selectedColor = colorSwatch.color; colorDialog.open() } }
                    }
                    Label { text: "also the colour picked up by Import"; color: root.muted; font.pixelSize: 12 }
                }
                Label { text: "Opacity" }
                RowLayout {
                    Layout.fillWidth: true
                    Slider { id: opacitySlider; from: 0.1; to: 1.0; Layout.fillWidth: true }
                    Label { text: Math.round(opacitySlider.value * 100) + "%"; color: root.muted; Layout.preferredWidth: 40 }
                }

                Section { text: "READING" }
                Label { text: "Continuous" }
                RowLayout {
                    Layout.fillWidth: true
                    Switch { id: continuousSwitch }
                    Label { text: "scroll through all pages (off: one page at a time)"; color: root.muted; font.pixelSize: 12 }
                }
                Label { text: "Hover delay" }
                RowLayout {
                    Layout.fillWidth: true
                    SpinBox { id: delayBox; from: 0; to: 2000; stepSize: 50; editable: true }
                    Label { text: "ms"; color: root.muted }
                }

                Section { text: "INTERACTIONS" }
                Repeater {
                    id: gestureRows
                    // reading order (the map from Python comes back sorted alphabetically)
                    model: ["hover", "click", "double_click", "hold_drag", "left_margin_click", "right_margin_click", "swipe_left", "swipe_right"]
                        .filter(g => g in backend.gestures)
                    RowLayout {
                        id: row
                        required property string modelData
                        readonly property string value: combo.currentValue
                        function reset() { combo.currentIndex = combo.indexOfValue(root.cfg.interactions[modelData]) }
                        Layout.columnSpan: 2
                        Layout.fillWidth: true
                        Label {
                            text: ({ hover: "Hover a word", click: "Click a word", double_click: "Double-click a word", hold_drag: "Hold and drag",
                                     swipe_left: "Swipe left", swipe_right: "Swipe right",
                                     left_margin_click: "Click left margin", right_margin_click: "Click right margin" })[row.modelData] || row.modelData
                            Layout.preferredWidth: 150
                        }
                        ComboBox {
                            id: combo
                            Layout.preferredWidth: 220
                            implicitHeight: 40
                            topInset: 0; bottomInset: 0
                            textRole: "text"; valueRole: "value"
                            model: backend.gestures[row.modelData].map(a => ({ value: a, text: a.replace(/_/g, " ") }))
                            Component.onCompleted: row.reset()
                        }
                    }
                }

                Section { text: "EXPORT" }
                Label { text: "Format" }
                ComboBox {
                    id: formatCombo
                    objectName: "formatCombo"
                    Layout.preferredWidth: 220
                    implicitHeight: 40
                    topInset: 0; bottomInset: 0
                    model: backend.exportFormats
                }
                Label { text: "Template" }
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: (root.cfg.templates[formatCombo.currentText] || "").split("\n").length + " lines"
                        color: root.muted; Layout.fillWidth: true
                    }
                    Button { text: "Edit…"; objectName: "editTemplate"; onClicked: templateDialog.open() }
                }
            }
        }
    }

    // own dialog: a long template needs the whole window and its own scrolling
    Dialog {
        id: templateDialog
        objectName: "templateDialog"
        property string format: formatCombo.currentText  // the format chosen in Settings, even before Save
        title: format + " export template"
        modal: true
        anchors.centerIn: parent
        width: Math.min(1000, root.width - 40)
        height: root.height - 40
        standardButtons: Dialog.Save | Dialog.Cancel
        background: Rectangle { color: root.surface; radius: 14 }
        onAboutToShow: templateArea.text = root.cfg.templates[format] || backend.defaultTemplates[format]
        onAccepted: backend.saveConfig({ templates: Object.assign({}, root.cfg.templates, { [format]: templateArea.text }) })

        ColumnLayout {
            anchors.fill: parent
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Label { text: "Insert:"; color: root.muted }
                Repeater {
                    model: [["{ID}", "unique id of the export"], ["{TITLE}", "PDF title"],
                            ["{DATE}", "today, e.g. 14 November 2026"], ["{CONTENT}", "the translated text"]]
                    Button {
                        required property var modelData
                        text: modelData[0]; flat: true
                        font.family: "monospace"
                        ToolTip.visible: hovered; ToolTip.delay: 500; ToolTip.text: modelData[1]
                        onClicked: { templateArea.insert(templateArea.cursorPosition, modelData[0]); templateArea.forceActiveFocus() }
                    }
                }
                Item { Layout.fillWidth: true }
                Button { text: "Reset to default"; flat: true; onClicked: templateArea.text = backend.defaultTemplates[templateDialog.format] }
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                background: Rectangle { radius: 6; color: "#f6f5f2"; border.color: root.line }
                TextArea {
                    id: templateArea
                    objectName: "templateArea"
                    font.family: "monospace"; font.pixelSize: 13
                    wrapMode: TextEdit.NoWrap
                    selectByMouse: true
                    background: null
                    padding: 10
                }
            }
        }
    }
}
