(function () {
  const container = document.querySelector("#room-scene");
  const status = document.querySelector("#room-status");
  if (!container || !status) return;

  let renderer;
  let camera;
  let scene;
  let tableLayer;
  let raycaster;
  let pointer;
  let selectTable;
  let availableTableIds = new Set();
  let tableMeshes = [];
  let radius = 21;
  let theta = 0.42;
  let phi = 0.92;
  let pointerStart = null;
  let dragged = false;
  let target;
  let roomGroup;

  const colors = {
    paleWood: 0xb98962,
    darkWood: 0x463d33,
    wall: 0xe9e6d9,
    trim: 0x6c5945,
    green: 0x3b7654,
    red: 0xb84f43,
    gray: 0x909a91
  };

  function box(parent, size, position, color, options = {}) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshStandardMaterial({ color, roughness: options.roughness ?? 0.78, metalness: options.metalness ?? 0 })
    );
    mesh.position.set(position[0], position[1], position[2]);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    parent.add(mesh);
    return mesh;
  }

  function cylinder(parent, radiusTop, radiusBottom, height, position, color, segments = 20) {
    const mesh = new THREE.Mesh(
      new THREE.CylinderGeometry(radiusTop, radiusBottom, height, segments),
      new THREE.MeshStandardMaterial({ color, roughness: 0.66 })
    );
    mesh.position.set(position[0], position[1], position[2]);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    parent.add(mesh);
    return mesh;
  }

  function labelSprite(text, background, width = 2.8) {
    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = 128;
    const context = canvas.getContext("2d");
    context.fillStyle = background;
    context.beginPath();
    context.roundRect(8, 8, 496, 112, 26);
    context.fill();
    context.fillStyle = "#ffffff";
    context.font = "700 34px Manrope, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(text, 256, 65, 460);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false, transparent: true }));
    sprite.scale.set(width, width * 0.25, 1);
    return sprite;
  }

  function buildRoom() {
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(17, 13),
      new THREE.MeshStandardMaterial({ color: 0xc7ad8b, roughness: 0.92 })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.025;
    floor.receiveShadow = true;
    roomGroup.add(floor);

    for (let x = -8; x <= 8; x += 1) {
      box(roomGroup, [0.018, 0.018, 12.8], [x, 0.002, 0], 0xb49776);
    }
    for (let z = -6; z <= 6; z += 1) {
      box(roomGroup, [16.8, 0.018, 0.018], [0, 0.003, z], 0xb49776);
    }

    box(roomGroup, [16.2, 5.2, 0.24], [0, 2.6, -6.35], colors.wall);
    box(roomGroup, [0.24, 5.2, 10.2], [-8.1, 2.6, -0.9], colors.wall);
    box(roomGroup, [0.24, 5.2, 7.8], [8.1, 2.6, -2.1], colors.wall);
    box(roomGroup, [16.3, 0.22, 0.32], [0, 0.12, -6.14], colors.trim);
    box(roomGroup, [16.3, 0.22, 0.32], [0, 0.12, 6.12], colors.trim);

    [-5.2, -1.7, 1.8].forEach((x) => {
      box(roomGroup, [2.45, 2.15, 0.08], [x, 3.25, -6.16], colors.trim);
      box(roomGroup, [2.17, 1.88, 0.035], [x, 3.25, -6.1], 0x9fc7c5, { roughness: 0.22, metalness: 0.08 });
      box(roomGroup, [0.07, 1.88, 0.09], [x, 3.25, -6.03], 0xf0e8d7);
      box(roomGroup, [2.17, 0.07, 0.09], [x, 3.25, -6.03], 0xf0e8d7);
    });

    const windowSign = labelSprite("DERAZA YONI", "#568f91", 2.65);
    windowSign.position.set(-2.1, 4.58, -5.94);
    roomGroup.add(windowSign);

    const stage = new THREE.Group();
    roomGroup.add(stage);
    box(stage, [4.3, 0.32, 2.25], [5.25, 0.17, -4.86], 0x664b3c);
    box(stage, [4.05, 0.08, 2.05], [5.25, 0.37, -4.86], 0x9b6046);
    box(stage, [0.65, 1.15, 0.5], [3.65, 0.98, -5.55], 0x262d2a);
    box(stage, [0.65, 1.15, 0.5], [6.85, 0.98, -5.55], 0x262d2a);
    cylinder(stage, 0.42, 0.42, 0.12, [5.05, 0.88, -5.3], 0x393d39, 28);
    cylinder(stage, 0.12, 0.12, 0.88, [5.05, 1.33, -5.3], 0x393d39, 20);
    cylinder(stage, 0.25, 0.25, 0.09, [4.58, 0.62, -5.3], 0xc4a673, 20);
    cylinder(stage, 0.25, 0.25, 0.09, [5.52, 0.62, -5.3], 0xc4a673, 20);

    const musician = new THREE.Group();
    musician.position.set(6.1, 0.42, -4.65);
    stage.add(musician);
    cylinder(musician, 0.22, 0.26, 0.82, [0, 0.66, 0], 0x496b61, 18);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.2, 18, 14), new THREE.MeshStandardMaterial({ color: 0xc9916e }));
    head.position.set(0, 1.2, 0);
    musician.add(head);
    cylinder(musician, 0.035, 0.035, 1.35, [-0.55, 0.9, 0.05], 0x393d39, 12);
    cylinder(musician, 0.12, 0.12, 0.08, [-0.55, 1.58, 0.05], 0x393d39, 16);
    const musicSign = labelSprite("MUSIQACHILAR", "#a75f42", 3.05);
    musicSign.position.set(5.25, 3.04, -5.94);
    roomGroup.add(musicSign);

    scene.add(roomGroup);
    scene.add(tableLayer);
  }

  function tableZone(table) {
    if (["T1", "T2"].includes(table.name)) return "window";
    if (["T5", "T6"].includes(table.name)) return "music";
    return "center";
  }

  function tablePosition(index) {
    const positions = [
      [-5.2, -3.7], [-1.7, -3.7],
      [-5.1, -0.35], [-1.7, -0.35],
      [1.8, -2.5], [4.8, -2.5]
    ];
    if (positions[index]) return positions[index];
    return [-5.3 + ((index - 6) % 4) * 3.45, 2.2 + Math.floor((index - 6) / 4) * 2.1];
  }

  function createChair(parent, angle, distance) {
    const x = Math.cos(angle) * distance;
    const z = Math.sin(angle) * distance;
    box(parent, [0.46, 0.14, 0.46], [x, 0.52, z], 0x526d5d);
    box(parent, [0.46, 0.5, 0.13], [x, 0.82, z - Math.sin(angle) * 0.2], 0x526d5d);
    [-0.16, 0.16].forEach((offset) => {
      box(parent, [0.055, 0.46, 0.055], [x + offset, 0.25, z], 0x554638);
    });
  }

  function clearTables() {
    tableLayer.traverse((object) => {
      if (object.geometry) object.geometry.dispose();
      if (object.material) {
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        materials.forEach((material) => {
          material.map?.dispose();
          material.dispose();
        });
      }
    });
    tableLayer.clear();
    tableMeshes = [];
  }

  function updateRoomTables(tables, availableTables, selectedTableId, selectedPartySize) {
    if (!renderer) return;
    clearTables();
    availableTableIds = new Set(availableTables.map((table) => table.id));
    partySize = selectedPartySize;
    tables.forEach((table, index) => {
      const [x, z] = tablePosition(index);
      const group = new THREE.Group();
      group.position.set(x, 0, z);
      const available = availableTableIds.has(table.id);
      const fits = table.seats >= partySize;
      const zone = tableZone(table);
      const statusColor = !fits ? colors.gray : available ? colors.green : colors.red;

      cylinder(group, 0.76, 0.8, 0.14, [0, 1.12, 0], available ? colors.paleWood : 0xa9a49a, 40);
      cylinder(group, 0.13, 0.2, 1.02, [0, 0.56, 0], colors.darkWood, 20);
      cylinder(group, 0.36, 0.36, 0.1, [0, 0.08, 0], colors.darkWood, 24);
      const tabletop = group.children[0];
      tabletop.userData.tableId = table.id;
      tableMeshes.push(tabletop);

      const seatCount = Math.min(Math.max(table.seats, 2), 8);
      for (let seat = 0; seat < seatCount; seat += 1) {
        createChair(group, (Math.PI * 2 * seat) / seatCount, 1.12);
      }

      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(0.96, selectedTableId === table.id ? 0.075 : 0.04, 10, 56),
        new THREE.MeshStandardMaterial({ color: selectedTableId === table.id ? 0xd3ef72 : statusColor, emissive: selectedTableId === table.id ? 0x62772e : 0x000000, roughness: 0.4 })
      );
      ring.rotation.x = Math.PI / 2;
      ring.position.y = 0.11;
      group.add(ring);

      const place = zone === "window" ? "DERAZA" : zone === "music" ? "MUSIQA" : "ZAL";
      const marker = labelSprite(`${table.name} · ${place}`, selectedTableId === table.id ? "#355e43" : fits && available ? "#4b6554" : "#777e78", 2.25);
      marker.position.set(0, 2.05, 0);
      group.add(marker);
      tableLayer.add(group);
    });
    status.hidden = tables.length > 0;
    status.textContent = tables.length ? "" : "Stollar ma’lumoti serverdan kutilmoqda...";
  }

  function positionCamera() {
    const sinPhi = Math.sin(phi);
    camera.position.set(
      target.x + radius * sinPhi * Math.sin(theta),
      target.y + radius * Math.cos(phi),
      target.z + radius * sinPhi * Math.cos(theta)
    );
    camera.lookAt(target);
  }

  function resetView() {
    radius = window.matchMedia("(max-width: 650px)").matches ? 25 : 21;
    theta = 0.42;
    phi = 0.92;
    positionCamera();
  }

  function setRoomStatus(text) {
    status.textContent = text;
    status.hidden = false;
  }

  function initRoomScene(onSelect) {
    selectTable = onSelect;
    if (!window.THREE) {
      setRoomStatus("3D kutubxonasi yuklanmadi. Stollarni ro‘yxatdan tanlashingiz mumkin.");
      return;
    }

    try {
      scene = new THREE.Scene();
      target = new THREE.Vector3(0, 1, 0);
      roomGroup = new THREE.Group();
      scene.background = new THREE.Color(0xdce6df);
      scene.fog = new THREE.Fog(0xdce6df, 25, 42);
      camera = new THREE.PerspectiveCamera(39, 1, 0.1, 80);
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.domElement.setAttribute("aria-hidden", "true");
      container.insertBefore(renderer.domElement, status);

      scene.add(new THREE.HemisphereLight(0xf5f6e9, 0x6d6757, 2.2));
      const sunlight = new THREE.DirectionalLight(0xffedcf, 2.7);
      sunlight.position.set(-5, 12, 7);
      sunlight.castShadow = true;
      sunlight.shadow.mapSize.set(1024, 1024);
      scene.add(sunlight);
      const windowLight = new THREE.PointLight(0x9ed1cb, 4, 16);
      windowLight.position.set(-3, 3.4, -4.6);
      scene.add(windowLight);

      tableLayer = new THREE.Group();
      raycaster = new THREE.Raycaster();
      pointer = new THREE.Vector2();
      buildRoom();
      resetView();

      const resize = () => {
        if (!renderer || !camera) return;
        const width = Math.max(container.clientWidth, 1);
        const height = Math.max(container.clientHeight, 1);
        camera.aspect = width / height;
        camera.fov = width < 520 ? 47 : 39;
        if (width < 520) radius = Math.max(radius, 24);
        camera.updateProjectionMatrix();
        renderer.setSize(width, height, false);
        positionCamera();
      };
      new ResizeObserver(resize).observe(container);
      resize();

      container.addEventListener("pointerdown", (event) => {
        pointerStart = { x: event.clientX, y: event.clientY };
        dragged = false;
        container.setPointerCapture(event.pointerId);
      });
      container.addEventListener("pointermove", (event) => {
        if (pointerStart) {
          const dx = event.clientX - pointerStart.x;
          const dy = event.clientY - pointerStart.y;
          if (Math.abs(dx) + Math.abs(dy) > 3) dragged = true;
          theta -= dx * 0.006;
          phi = THREE.MathUtils.clamp(phi + dy * 0.004, 0.48, 1.25);
          pointerStart = { x: event.clientX, y: event.clientY };
          positionCamera();
          return;
        }
        const bounds = renderer.domElement.getBoundingClientRect();
        pointer.set(((event.clientX - bounds.left) / bounds.width) * 2 - 1, -((event.clientY - bounds.top) / bounds.height) * 2 + 1);
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObjects(tableMeshes, false)[0];
        container.style.cursor = hit && availableTableIds.has(hit.object.userData.tableId) ? "pointer" : "grab";
      });
      container.addEventListener("pointerup", (event) => {
        if (pointerStart && !dragged) {
          const bounds = renderer.domElement.getBoundingClientRect();
          pointer.set(((event.clientX - bounds.left) / bounds.width) * 2 - 1, -((event.clientY - bounds.top) / bounds.height) * 2 + 1);
          raycaster.setFromCamera(pointer, camera);
          const hit = raycaster.intersectObjects(tableMeshes, false)[0];
          if (hit) selectTable?.(hit.object.userData.tableId);
        }
        pointerStart = null;
        dragged = false;
      });
      container.addEventListener("pointercancel", () => { pointerStart = null; });
      container.addEventListener("wheel", (event) => {
        event.preventDefault();
        radius = THREE.MathUtils.clamp(radius + event.deltaY * 0.012, 13, 31);
        positionCamera();
      }, { passive: false });
      document.querySelector("#room-reset")?.addEventListener("click", resetView);

      window.updateRoomTables = updateRoomTables;
      window.setRoomStatus = setRoomStatus;
      status.hidden = true;
      const render = () => {
        renderer.render(scene, camera);
        requestAnimationFrame(render);
      };
      render();
    } catch {
      renderer?.dispose();
      renderer = null;
      setRoomStatus("3D ko‘rinishni ishga tushirib bo‘lmadi. Stollarni ro‘yxatdan tanlang.");
    }
  }

  window.initRoomScene = initRoomScene;
})();