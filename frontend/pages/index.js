import { useState } from 'react'
import axios from 'axios'

export default function Home(){
  const [file, setFile] = useState(null)
  const [parsed, setParsed] = useState(null)
  const upload = async () =>{
    const fd = new FormData();
    fd.append('file', file)
    const res = await axios.post(process.env.NEXT_PUBLIC_API + '/resume/parse', fd)
    setParsed(res.data.parsed)
  }
  return (
    <div className="p-8 max-w-3xl mx-auto">
      <h1 className="text-3xl font-bold">ResumePro — Instant Rewrite</h1>
      <input type="file" onChange={(e)=>setFile(e.target.files[0])} />
      <button onClick={upload} className="px-4 py-2 bg-blue-600 text-white rounded">Upload & Parse</button>
      {parsed && <pre className="mt-4 bg-gray-100 p-4">{JSON.stringify(parsed, null, 2)}</pre>}
    </div>
  )
}