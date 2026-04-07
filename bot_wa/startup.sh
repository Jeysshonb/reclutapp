#!/bin/bash
find /home -name "SingletonLock" -delete 2>/dev/null || true
exec node index.js
 
