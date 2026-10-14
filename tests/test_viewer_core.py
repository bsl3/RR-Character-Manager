"""Texture/geometry safety and depth/UV tests independent of private assets."""
import struct
import unittest
import numpy as np
from PIL import Image
from wcm.preview3d import PreviewMesh, PreviewMaterial, PreviewDecodeError, list_models, default_model, ModelVariant
from wcm.brrescore import _object, texture_srt, _texture_coordinates, _material_state, _bind_influences, _bone_nodes
from wcm.gxtexture import decode_texture
from wcm.raster import render_mesh, wrap


class TextureFormats(unittest.TestCase):
    def test_supported_tiled_formats_and_alpha(self):
        samples=[(0,b'\xff'*32,(255,255,255,255)),(1,b'\x70'*32,(112,112,112,255)),
                 (2,b'\xa5'*32,(85,85,85,170)),(3,b'\x80\x22'*16,(34,34,34,128)),
                 (4,b'\xf8\x00'*16,(255,0,0,255)),(5,b'\x80\x1f'*16,(0,0,255,255)),
                 (6,b'\x80\xff'*16+b'\x33\x66'*16,(255,51,102,128)),
                 (8,b'\x00'*32,(1,2,3,4)),(9,b'\x00'*32,(1,2,3,4)),(10,b'\x00'*32,(1,2,3,4))]
        for fmt,raw,expected in samples:
            with self.subTest(fmt=fmt):
                self.assertEqual(decode_texture(raw,1,1,fmt,palette=[(1,2,3,4)]).getpixel((0,0)),expected)

    def test_cmpr_subblocks_and_transparency(self):
        red=struct.pack('>HH',0xf800,0)+bytes(4)
        blue=struct.pack('>HH',0x001f,0)+bytes(4)
        clear=struct.pack('>HH',0,0)+b'\xff'*4
        im=decode_texture(red+blue+clear+red,8,8,14)
        self.assertEqual(im.getpixel((0,0)),(255,0,0,255))
        self.assertEqual(im.getpixel((4,0)),(0,0,255,255))
        self.assertEqual(im.getpixel((0,4)),(0,0,0,0))

    def test_invalid_texture_does_not_allocate_or_guess(self):
        for args in [(b'',4,4,5),(b'',3000,1,5),(bytes(32),4,4,7),(bytes(32),4,4,8)]:
            with self.assertRaises(ValueError): decode_texture(*args)


class GeometryCore(unittest.TestCase):
    def bone_blob(self):
        blob=bytearray(0x200)
        for at,nid,srt in ((0,4,(2,2,2,0,0,90,10,20,30)),
                           (0x100,5,(0,0,0,0,0,0,1,2,3))):
            struct.pack_into('>i',blob,at+0x10,nid)
            struct.pack_into('>9f',blob,at+0x20,*srt)
            # Deliberately stale cached frame and independent inverse bind.
            struct.pack_into('>12f',blob,at+0x70,*np.eye(4)[:3].ravel())
            struct.pack_into('>12f',blob,at+0xa0,*np.eye(4)[:3].ravel())
        struct.pack_into('>i',blob,0x15c,-0x100)
        return blob

    def test_bone_hierarchy_rebuilds_stale_cache_and_preserves_zero_scale(self):
        blob=self.bone_blob()
        nodes,inverse=_bone_nodes(bytes(blob),[('child',0x100),('root',0)],len(blob),[])
        self.assertTrue(np.allclose(nodes[4]@(1,0,0,1),(10,22,30,1)))
        # Parent rotation/scale applies to child translation; its collapsed
        # geometry must not be expanded using the stale cached identity.
        self.assertTrue(np.allclose(nodes[5]@(900,900,900,1),(6,22,36,1)))
        self.assertTrue(np.allclose(inverse[5],np.eye(4)))

    def test_invalid_bone_hierarchy_is_rejected(self):
        for relative,message in ((-0x80,'Unknown bone parent'),(0x100,'Cycle')):
            blob=self.bone_blob()
            struct.pack_into('>i',blob,0x5c,relative)
            with self.assertRaisesRegex(PreviewDecodeError,message):
                _bone_nodes(bytes(blob),[('root',0),('child',0x100)],len(blob),[])

    def test_single_influence_and_weighted_envelope_use_distinct_spaces(self):
        bind=np.eye(4);bind[:3,3]=[10,20,30]
        other=np.eye(4);other[:3,3]=[-10,10,5]
        nodes={4:bind,5:other,6:None};inverse={4:np.linalg.inv(bind),5:np.linalg.inv(other),6:None}
        _bind_influences(nodes,inverse,[(7,[(4,1.)]),(8,[(4,.25),(5,.75)]),(9,[(6,1.)])])
        self.assertTrue(np.allclose(nodes[7]@(1,2,3,1),(11,22,33,1)))
        self.assertTrue(np.allclose(nodes[8]@(1,2,3,1),(1,2,3,1)))
        self.assertIsNone(nodes[9])
        blob=self.object_blob();mesh=PreviewMesh('unused',[],[])
        _object(blob,0,len(blob),[[(0,0,0)]*3],[[(0,0)]*3],nodes,mesh,0)
        nodes[4]=None
        with self.assertRaisesRegex(PreviewDecodeError,'Invalid bind matrix required'):
            _object(blob,0,len(blob),[[(0,0,0)]*3],[[(0,0)]*3],nodes,PreviewMesh('bad',[],[]),0)
    def test_xlu_material_can_blend_and_write_depth_like_biker_and_snooza(self):
        blob=bytearray(0x100);struct.pack_into('>i',blob,0x3c,0x80)
        block=bytes.fromhex('61f31eff9b614000001761fe00ffe361410034a16142000000')
        blob[0x80:0x80+len(block)]=block
        mat=PreviewMaterial('xlu',translucent=True)
        _material_state(bytes(blob),0,len(blob),mat,[])
        self.assertTrue(mat.depth_test);self.assertTrue(mat.depth_write)
        self.assertEqual(mat.depth_func,3);self.assertTrue(mat.blend_enabled)
        self.assertEqual((mat.blend_src,mat.blend_dst),(4,5))
        self.assertEqual(mat.alpha_test,(6,155,3,255,0))

    def test_texture_srt_mirrors_eye_halves_and_honors_pivots(self):
        # Mario/Luigi eye UVs each span half the atlas and use 2x S scale.
        matrix=texture_srt(2,1,0,0,0)
        self.assertTrue(np.allclose(matrix@(.25,.3,1),(.5,.3,1)))
        self.assertTrue(np.allclose(matrix@(.75,.3,1),(1.5,.3,1)))
        self.assertTrue(np.allclose(wrap(np.array([.5,1.5]),2),[.5,.5]))
        self.assertTrue(np.allclose(texture_srt(1,2,0,0,0)@(0,1,1),(0,1,1)))
        for mode in (0,2):
            self.assertTrue(np.allclose(texture_srt(1,1,90,0,0,mode)@(.5,.5,1),(.5,.5,1)))
        self.assertTrue(np.allclose(texture_srt(1,1,90,0,0,1)@(0,1,1),(0,1,1)))
        self.assertTrue(np.allclose(texture_srt(1,1,0,.2,.3)@(0,0,1),(-.2,.3,1)))

    def test_material_static_srt_and_xf_uv_channel_are_read_with_bounds(self):
        blob=bytearray(0x600);struct.pack_into('>i',blob,0x3c,0x400)
        struct.pack_into('>II5f',blob,0x1a0,13,0,2,1,0,0,0)
        # One XF register for texgen0 sourcing TexCoord1 (row6).
        blob[0x4e0:0x4e9]=b'\x10'+struct.pack('>HHI',0,0x1040,6<<7)
        material=PreviewMaterial('eyes');warnings=[]
        _texture_coordinates(bytes(blob),0,len(blob),0x500,material,warnings)
        self.assertEqual(material.uv_channel,1)
        self.assertEqual(material.uv_matrix[0,0],2)
        with self.assertRaises(PreviewDecodeError):
            _texture_coordinates(bytes(blob),0,0x1a8,0x500,material,warnings)

    def test_material_selects_uv1_and_applies_transform_per_corner(self):
        blob=bytearray(self.object_blob())
        struct.pack_into('>I',blob,16,3<<2)
        struct.pack_into('>hh',blob,0x50,-1,0)
        material=PreviewMaterial('eyes',uv_channel=1,uv_matrix=texture_srt(2,1,0,0,0))
        mesh=PreviewMesh('UV1',[],[],materials=[material])
        _object(bytes(blob),0,len(blob),[[(0,0,0),(1,0,0),(0,1,0)]],
                [[(0,0),(.5,0),(0,1)]],{4:np.eye(4)},mesh,0)
        self.assertEqual(mesh.uvs,[(0,0),(1,0),(0,1)])

    def test_model_default_avoids_lod_even_when_lod_larger(self):
        variants=[ModelVariant('model_lod',0,5000,11,True),ModelVariant('model',5,1000,11,False)]
        self.assertEqual(default_model(variants),1)

    def test_model_default_prefers_normal_over_larger_alternates(self):
        variants=[ModelVariant('model_alt',0,5000,11,False),ModelVariant('model',5,1000,11,False),
                  ModelVariant('hair',9,10000,11,False)]
        self.assertEqual(default_model(variants),1)

    def test_dictionary_parsing_rejects_signature_only_fake_resources(self):
        with self.assertRaises(PreviewDecodeError): list_models(b'bres'+bytes(32)+b'MDL0'+bytes(150))

    def object_blob(self,weighted=False):
        blob=bytearray(0xa0)
        struct.pack_into('>I',blob,0,len(blob));struct.pack_into('>i',blob,8,-1 if weighted else 4)
        struct.pack_into('>II',blob,12,(3<<9)|(1 if weighted else 0),3)
        struct.pack_into('>hh',blob,0x48,0,-1);struct.pack_into('>h',blob,0x50,0)
        stream=bytearray()
        if weighted: stream+=b'\x20'+struct.pack('>HH',4,0xb000)
        stream+=b'\x90\x00\x03'
        for index in range(3): stream+=(b'\0' if weighted else b'')+struct.pack('>HH',index,index)
        struct.pack_into('>I',blob,0x24,len(stream));struct.pack_into('>i',blob,0x2c,0x70-0x24)
        blob[0x70:0x70+len(stream)]=stream
        return bytes(blob)

    def test_rigid_and_matrix_palette_use_same_bind_transform_with_uv_seams(self):
        matrix=np.eye(4);matrix[:3,3]=[10,20,30]
        for weighted in (False,True):
            mesh=PreviewMesh('test',[],[])
            blob=self.object_blob(weighted)
            _object(blob,0,len(blob),[[(0,0,0),(1,0,0),(0,1,0)]],[[(0,0),(1,0),(0,1)]],{4:matrix},mesh,0)
            self.assertEqual(mesh.vertices[0],(10,20,30))
            self.assertEqual(mesh.vertices[1],(11,20,30))
            self.assertEqual(mesh.uvs,[(0,0),(1,0),(0,1)])
            self.assertEqual(len(mesh.triangles),1)

    def test_missing_matrix_load_is_reported_instead_of_displaced_geometry(self):
        blob=bytearray(self.object_blob(True));blob[0x70]=0
        with self.assertRaises(PreviewDecodeError):
            _object(bytes(blob),0,len(blob),[[(0,0,0)]*3],[[(0,0)]*3],{},PreviewMesh('bad',[],[]),0)


class RasterAccuracy(unittest.TestCase):
    def test_blended_front_geometry_occludes_backfaces_with_depth_updates(self):
        front=PreviewMaterial('front',Image.new('RGBA',(1,1),(255,0,0,255)),translucent=True,depth_write=True)
        back=PreviewMaterial('back',Image.new('RGBA',(1,1),(0,0,255,255)),translucent=True,depth_write=True)
        mesh=PreviewMesh('overlap',self.square(1)+self.square(-1),
            [(0,1,2,0),(0,2,3,0),(4,5,6,1),(4,6,7,1)],[(0,0)]*8,[front,back])
        self.assertEqual(tuple(render_mesh(mesh,50,50,0,0)[25,25]),(255,0,0,255))

    def test_gx_alpha_logic_and_blend_factors(self):
        from wcm.renderstate import alpha_pass,blend_colors
        values=np.array([0,154,155,254,255],dtype=np.uint8)
        self.assertEqual(alpha_pass(values,(6,155,3,255,0)).tolist(),[False,False,True,True,True])
        self.assertEqual(alpha_pass(values,(2,0,2,255,1)).tolist(),[True,False,False,False,True])
        src=np.array([[[255,0,0,128]]],dtype=np.uint8);dst=np.array([[[0,0,255,255]]],dtype=np.uint8)
        m=PreviewMaterial('alpha',blend_enabled=True)
        self.assertEqual(blend_colors(src,dst,m).tolist(),[[[128,0,127]]])
        m.blend_src=1;m.blend_dst=0
        self.assertEqual(blend_colors(src,dst,m).tolist(),[[[255,0,0]]])
        m.blend_subtract=True;m.blend_src=m.blend_dst=0
        self.assertEqual(blend_colors(src,dst,m).tolist(),[[[0,0,255]]])
    def test_gx_culling_hides_inside_faces_but_none_draws_both_sides(self):
        material=PreviewMaterial('cull',Image.new('RGBA',(1,1),(255,0,0,255)),cull=2)
        mesh=PreviewMesh('front',[(-1,-1,0),(0,1,0),(1,-1,0)],[(0,1,2,0)],[(0,0)]*3,[material])
        self.assertEqual(tuple(render_mesh(mesh,50,50,0,0)[25,25]),(255,0,0,255))
        mesh.triangles=[(2,1,0,0)]
        self.assertEqual(tuple(render_mesh(mesh,50,50,0,0)[25,25]),(16,27,43,255))
        material.cull=0
        self.assertEqual(tuple(render_mesh(mesh,50,50,0,0)[25,25]),(255,0,0,255))
    def square(self,z=0):
        return [(-1,-1,z),(1,-1,z),(1,1,z),(-1,1,z)]

    def test_uv_mapping_uses_actual_texture_and_depth_occludes_far_triangle(self):
        texture=Image.new('RGBA',(2,2));texture.putdata([(255,0,0,255),(0,255,0,255),(0,0,255,255),(255,255,0,255)])
        mesh=PreviewMesh('UV test',self.square(),[(0,1,2,0),(0,2,3,0)],[(0,1),(1,1),(1,0),(0,0)],[PreviewMaterial('real',texture)])
        out=render_mesh(mesh,100,100,0,0)
        self.assertEqual(tuple(out[30,30]),(255,0,0,255))
        self.assertEqual(tuple(out[30,70]),(0,255,0,255))
        self.assertEqual(tuple(out[70,30]),(0,0,255,255))
        # A nearer magenta quad must occlude all texture pixels in either draw order.
        mesh.vertices+=self.square(1);mesh.uvs += [(0,0)]*4
        mesh.materials.append(PreviewMaterial('near',Image.new('RGBA',(1,1),(255,0,255,255))))
        mesh.triangles=[(4,5,6,1),(4,6,7,1)]+mesh.triangles
        self.assertEqual(tuple(render_mesh(mesh,100,100,0,0)[30,30]),(255,0,255,255))

    def test_cutout_leaves_background_and_repeat_mirror_are_correct(self):
        mesh=PreviewMesh('alpha',self.square(),[(0,1,2,0),(0,2,3,0)],[(0,0)]*4,
                         [PreviewMaterial('transparent',Image.new('RGBA',(1,1),(255,0,0,0)))])
        self.assertEqual(tuple(render_mesh(mesh,50,50,0,0)[25,25]),(16,27,43,255))
        self.assertTrue(np.allclose(wrap(np.array([-0.25,1.25]),1),[.75,.25]))
        self.assertTrue(np.allclose(wrap(np.array([-0.25,1.25]),2),[.25,.75]))

    def test_cancellation_returns_without_publishing_incomplete_frame(self):
        mesh=PreviewMesh('cancel',self.square(),[(0,1,2,0)],[(0,0)]*4,[PreviewMaterial('gray')])
        self.assertIsNone(render_mesh(mesh,50,50,cancel=lambda:True))

if __name__=='__main__': unittest.main()
