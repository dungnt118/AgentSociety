import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

const envFilePath = path.join(rootDir, 'portainer.env');
const stackFilePath = path.join(rootDir, 'portainer-stack.yml');

if (!fs.existsSync(envFilePath)) {
  console.error(`[LOI] Khong tim thay file cau hinh: ${envFilePath}`);
  console.error(' -> Chay lenh sau tai thu muc goc roi dien cac bien bi mat:');
  console.error('    Copy-Item portainer.env.example portainer.env');
  process.exit(1);
}

if (!fs.existsSync(stackFilePath)) {
  console.error(`[LOI] Khong tim thay file compose stack: ${stackFilePath}`);
  process.exit(1);
}

const envRaw = fs.readFileSync(envFilePath, 'utf8');
const stackContent = fs.readFileSync(stackFilePath, 'utf8');

// Cac bien chi phuc vu may local di deploy — TUYET DOI khong day len Portainer Stack runtime
const DEPLOY_ONLY_ENV_KEYS = new Set([
  'DOCKERHUB_TOKEN',
  'DOCKERHUB_USERNAME',
  'PORTAINER_ACCESS_TOKEN',
  'PORTAINER_URL',
  'PORTAINER_ENDPOINT_ID',
  'PORTAINER_STACK_ID',
  'PORTAINER_STACK_NAME',
  'SKIP_DOCKER_PUSH',
  'AUTO_PUSH_DOCKERHUB',
  'COMPOSE_PROJECT_NAME',
  'DOCKER_IMAGE_REPO',
  'AGENTSOCIETY_RUNTIME_TAG',
  'AGENTSOCIETY_GATEWAY_TAG'
]);

const envMap = new Map();
const envList = [];
let skippedDeployOnlyCount = 0;

for (const line of envRaw.split(/\r?\n/)) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith('#')) continue;
  const eqIdx = trimmed.indexOf('=');
  if (eqIdx > 0) {
    const key = trimmed.slice(0, eqIdx).trim();
    let val = trimmed.slice(eqIdx + 1).trim();
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    } else {
      const hashIdx = val.indexOf('#');
      if (hashIdx >= 0) {
        val = val.slice(0, hashIdx).trim();
      }
    }
    envMap.set(key, val);
    if (DEPLOY_ONLY_ENV_KEYS.has(key)) {
      skippedDeployOnlyCount += 1;
    } else {
      envList.push({ name: key, value: val });
    }
  }
}

const portainerUrl = (envMap.get('PORTAINER_URL') || 'https://portainer.demego.vn').replace(/\/+$/, '');
const apiKey = envMap.get('PORTAINER_ACCESS_TOKEN');
const endpointId = Number(envMap.get('PORTAINER_ENDPOINT_ID') || 3);
const stackId = (envMap.get('PORTAINER_STACK_ID') || '').trim();
const stackName = envMap.get('PORTAINER_STACK_NAME') || 'agentsociety2';

const repo = envMap.get('DOCKER_IMAGE_REPO') || 'dungnt118/freepbx';
const runtimeTag = envMap.get('AGENTSOCIETY_RUNTIME_TAG') || 'agentsociety2-runtime';
const gatewayTag = envMap.get('AGENTSOCIETY_GATEWAY_TAG') || 'agentsociety2-gateway';
const runtimeImage = envMap.get('AGENTSOCIETY_RUNTIME_IMAGE') || `${repo}:${runtimeTag}`;
const gatewayImage = envMap.get('AGENTSOCIETY_GATEWAY_IMAGE') || `${repo}:${gatewayTag}`;
const dockerUsername = envMap.get('DOCKERHUB_USERNAME') || 'dungnt118';
const dockerPassword = envMap.get('DOCKERHUB_TOKEN');

if (!apiKey) {
  console.error('[LOI] Khong tim thay PORTAINER_ACCESS_TOKEN trong file portainer.env!');
  process.exit(1);
}
if (!stackId) {
  console.error('[LOI] Chua cau hinh PORTAINER_STACK_ID trong portainer.env!');
  console.error(' -> Hay tao Stack tren Portainer Web UI voi portainer-stack.yml, sau do dien PORTAINER_STACK_ID.');
  process.exit(1);
}

async function pullImageOnPortainer(imageName) {
  console.log(` -> Dang pull image ve Docker host Portainer: ${imageName} ...`);
  const encodedImage = encodeURIComponent(imageName);
  const pullUrl = `${portainerUrl}/api/endpoints/${endpointId}/docker/images/create?fromImage=${encodedImage}`;
  const pullHeaders = { 'X-API-Key': apiKey };

  if (dockerUsername && dockerPassword) {
    const authJson = JSON.stringify({
      username: dockerUsername,
      password: dockerPassword,
      serveraddress: 'https://index.docker.io/v1/'
    });
    pullHeaders['X-Registry-Auth'] = Buffer.from(authJson).toString('base64');
  }

  try {
    const pullRes = await fetch(pullUrl, { method: 'POST', headers: pullHeaders });
    if (!pullRes.ok) {
      const pullErr = await pullRes.text();
      console.warn(`[CANH BAO] Pull ${imageName} tra HTTP ${pullRes.status}: ${pullErr}`);
      return;
    }
    const streamText = await pullRes.text();
    let streamErr = '';
    for (const line of streamText.split(/\r?\n/)) {
      if (!line.trim()) continue;
      try {
        const evt = JSON.parse(line);
        if (evt.error || evt.errorDetail) {
          streamErr = evt.error || evt.errorDetail?.message || 'Unknown error';
        }
      } catch {}
    }
    if (streamErr) {
      console.warn(`[CANH BAO] Docker daemon bao loi khi pull ${imageName}: ${streamErr}`);
    } else {
      console.log(`[OK] Da pull xong '${imageName}' ve host Portainer!`);
    }
  } catch (err) {
    console.warn(`[CANH BAO] Loi ngoai le khi pull ${imageName}: ${err.message}`);
  }
}

console.log('=================================================================');
console.log('   AgentSociety2 - Portainer Production Deploy (Native REST API)');
console.log('=================================================================');
console.log(` - Server Portainer:  ${portainerUrl}`);
console.log(` - Stack Name:        ${stackName} (#${stackId})`);
console.log(` - Endpoint ID:       ${endpointId}`);
console.log(` - Runtime Image:     ${runtimeImage}`);
console.log(` - Gateway Image:     ${gatewayImage}`);
console.log(` - So bien moi truong: ${envList.length} (da loc ${skippedDeployOnlyCount} bien deploy-only o local)`);
console.log('');

try {
  console.log(' -> Dang kiem tra ket noi den Stack tren Portainer...');
  const getUrl = `${portainerUrl}/api/stacks/${stackId}?endpointId=${endpointId}`;
  const getRes = await fetch(getUrl, {
    method: 'GET',
    headers: { 'X-API-Key': apiKey }
  });

  if (!getRes.ok) {
    const errText = await getRes.text();
    console.error(`[LOI] Khong the lay thong tin Stack tu Portainer! HTTP ${getRes.status}: ${errText}`);
    process.exit(1);
  }

  const stackInfo = await getRes.json();
  console.log(` -> Stack hien tai: '${stackInfo.Name}' | Type: ${stackInfo.Type} | Status: ${stackInfo.Status}`);
  console.log('');

  console.log('=== TASK 1: PULL IMAGES DOC LAP QUA DOCKER API ===');
  await pullImageOnPortainer(runtimeImage);
  await pullImageOnPortainer(gatewayImage);
  console.log('');

  console.log('=== TASK 2: REDEPLOY VA CAP NHAT STACK TREN PORTAINER ===');
  const putUrl = `${portainerUrl}/api/stacks/${stackId}?endpointId=${endpointId}`;
  const putPayload = {
    stackFileContent: stackContent,
    env: envList,
    prune: true,
    pullImage: false
  };

  const putRes = await fetch(putUrl, {
    method: 'PUT',
    headers: {
      'X-API-Key': apiKey,
      'Content-Type': 'application/json; charset=utf-8'
    },
    body: JSON.stringify(putPayload)
  });

  if (!putRes.ok) {
    const errBody = await putRes.text();
    console.error(`[LOI] Portainer tu choi cap nhat Stack! HTTP ${putRes.status}: ${errBody}`);
    process.exit(1);
  }

  const putData = await putRes.json();
  console.log('[OK] Portainer Production da cap nhat va redeploy Stack thanh cong!');
  console.log(` -> Stack ID: ${putData.Id} | Status: ${putData.Status} | UpdateDate: ${new Date(putData.UpdateDate * 1000).toLocaleString('vi-VN')}`);
} catch (err) {
  console.error(`[LOI] Qua trinh deploy Portainer gap loi ngoai le: ${err.message}`);
  process.exit(1);
}
