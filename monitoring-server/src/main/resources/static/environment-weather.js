/* Location-based weather display only; never changes device weather/LED mode. */
(function(root){
 const cache=new Map();let activeKey=null;
 function weatherName(code){if(code===0)return '맑음';if([1,2,3].includes(code))return '구름/흐림';if([45,48].includes(code))return '안개';if([71,73,75,77,85,86].includes(code))return '눈';if([95,96,99].includes(code))return '뇌우';if([51,53,55,56,57,61,63,65,66,67,80,81,82].includes(code))return '비';return '정보 없음';}
 function show(weather,wind,pm){for(const [id,value]of [['envWeather',weather],['envWind',wind],['envPm10',pm]]){const el=document.getElementById(id);if(el){el.textContent=value;el.title='설치 좌표 기준 Open-Meteo 기상·대기질 데이터 (현장 실측값 아님)';}}}
 function draw(entry){show(entry.weather,entry.wind,entry.pm);}
 async function read(url){const r=await fetch(url,{credentials:'omit',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(10000)});if(!r.ok)throw Error('Weather HTTP '+r.status);return r.json();}
 function update(rail){
  if(!rail){activeKey=null;show('난간 선택','-- m/s','--');return;}
  const lat=rail.latitude,lng=rail.longitude;
  if(lat==null||lng==null||!Number.isFinite(Number(lat))||!Number.isFinite(Number(lng))){activeKey=null;show('설치 좌표 미등록','-- m/s','--');return;}
  const key=Number(lat).toFixed(5)+','+Number(lng).toFixed(5);activeKey=key;
  let entry=cache.get(key);if(entry&&(entry.pending||Date.now()<entry.expires)){draw(entry);return;}
  entry={weather:'조회 중…',wind:'조회 중…',pm:'조회 중…',pending:true,expires:0};cache.set(key,entry);draw(entry);
  if(cache.size>64)cache.delete(cache.keys().next().value);
  const q='latitude='+encodeURIComponent(lat)+'&longitude='+encodeURIComponent(lng);
  Promise.allSettled([
   read('https://api.open-meteo.com/v1/forecast?'+q+'&current=temperature_2m,weather_code,wind_speed_10m&wind_speed_unit=ms'),
   read('https://air-quality-api.open-meteo.com/v1/air-quality?'+q+'&current=pm10')
  ]).then(([w,a])=>{
   const c=w.status==='fulfilled'?w.value.current:null,p=a.status==='fulfilled'?a.value.current?.pm10:null;
   entry.weather=c&&Number.isFinite(c.weather_code)?weatherName(c.weather_code)+(Number.isFinite(c.temperature_2m)?' · '+c.temperature_2m+'°C':''):'조회 실패';
   entry.wind=c&&Number.isFinite(c.wind_speed_10m)?c.wind_speed_10m+' m/s':'조회 실패';
   entry.pm=Number.isFinite(p)?p+' μg/m³':'조회 실패';
   entry.pending=false;entry.expires=Date.now()+(w.status==='fulfilled'&&a.status==='fulfilled'?600000:60000);
   if(activeKey===key)draw(entry);
  });
 }
 root.EnvironmentWeather={update,weatherName};
})(globalThis);
